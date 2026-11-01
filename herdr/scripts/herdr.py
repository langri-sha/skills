#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

OK = 0
FAILED = 1
USAGE = 2
NOT_FOUND = 3
NO_SEAT = 4
SPACE_EXISTS = 5

Result = namedtuple("Result", "code out err")


class Fail(Exception):
    def __init__(self, code, error, reason, **extra):
        super().__init__(reason)
        self.code = code
        self.error = error
        self.reason = reason
        self.extra = extra


def subprocess_runner(argv, timeout):
    try:
        done = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return Result(127, "", f"{argv[0]}: command not found")
    except subprocess.TimeoutExpired:
        return Result(124, "", f"{argv[0]}: timed out after {timeout}s")
    return Result(done.returncode, done.stdout, done.stderr)


class System:
    def __init__(self, runner=None, environ=None, pid=None, home=None):
        self.runner = runner or subprocess_runner
        self.environ = os.environ if environ is None else environ
        self.pid = os.getpid() if pid is None else pid
        self.home = Path(home) if home else Path.home()

    def run(self, argv, timeout=30):
        return self.runner(list(argv), timeout)

    def json(self, argv, timeout=30):
        result = self.run(argv, timeout)
        return parse_json(result.out), result

    def env(self, name):
        return self.environ.get(name) or None


def parse_json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def error_of(result):
    for text in (result.err, result.out):
        data = parse_json(text)
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            return data["error"]
    return {"message": (result.err or result.out).strip()}


def fail_from(result, what, target=None):
    error = error_of(result)
    kind = error.get("kind") or error.get("code") or ""
    reason = error.get("message") or f"{what} exited {result.code}"
    code = NOT_FOUND if "not_found" in kind or result.code == 3 else FAILED
    return Fail(
        code, kind or "command_failed", reason, command=what, target=target
    )


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    tty: str
    args: str


PROC_LINE = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\S+)\s*(.*)$")


def normalize_tty(tty):
    tty = (tty or "").strip()
    if tty in ("", "?", "??", "-"):
        return ""
    return tty.removeprefix("/dev/")


def process_table(system):
    result = system.run(["ps", "-A", "-o", "pid=,ppid=,tty=,args="])
    table = {}
    for line in result.out.splitlines():
        match = PROC_LINE.match(line)
        if match:
            pid, ppid, tty, args = match.groups()
            table[int(pid)] = Proc(int(pid), int(ppid), normalize_tty(tty), args)
    return table


def controlling_tty(procs, pid):
    seen = set()
    while pid in procs and pid > 1 and pid not in seen:
        seen.add(pid)
        if procs[pid].tty:
            return procs[pid].tty
        pid = procs[pid].ppid
    return ""


def descendants(procs, root):
    children = {}
    for proc in procs.values():
        children.setdefault(proc.ppid, []).append(proc.pid)
    order, queue = [], [root]
    while queue:
        pid = queue.pop(0)
        if pid in procs and pid not in order:
            order.append(pid)
        queue.extend(sorted(children.get(pid, [])))
    return [procs[pid] for pid in order]


def agent_kind(raw):
    raw = (raw or "").lower()
    if raw.startswith("claude"):
        return "claude"
    if raw.startswith("codex"):
        return "codex"
    return raw or None


def tab_of_terminal(layout, terminal):
    for space in (layout or {}).get("spaces", []):
        for tab in space.get("tabs", []):
            for found in tab.get("terminals", []):
                if found.get("terminal") == terminal:
                    return space, tab
    return None, None


def session_comparison(system, recorded, source):
    expected = system.env("CLAUDE_CODE_SESSION_ID")
    if expected is None:
        return None, "CLAUDE_CODE_SESSION_ID is not set"
    if recorded is None:
        return None, source
    return recorded == expected, None


class AppBackend:
    name = "app"

    def __init__(self, system):
        self.system = system

    def hc(self, *args, timeout=30):
        return self.system.json(["hc", *args], timeout)

    def record(self, target):
        data, result = self.hc("get", target, "--json")
        if result.code != 0 or not isinstance(data, dict):
            raise fail_from(result, "hc get", target)
        return data

    def identity(self, target):
        record = self.record(target)
        labels = record.get("labels") or {}
        status = record.get("status") or {}
        return {
            "target": record.get("address") or target,
            "agent": agent_kind(status.get("app")),
            "name": labels.get("claude.name") or record.get("name"),
            "state": record.get("state"),
            "status": status.get("state"),
            "dialog": dialog_of(status),
            "labels": labels,
            "cwd": labels.get("claude.cwd") or record.get("cwd"),
            "parent": record.get("parent"),
            "where": labels.get("where"),
            "root_pid": record.get("pid"),
            "session": labels.get("claude.session"),
            "session_source": "label",
            "model": labels.get("claude.model"),
            "effort": labels.get("claude.effort"),
            "terminal_args": record.get("argv") or [],
        }

    def read(self, target, lines, wait_timeout):
        def fetch():
            data, result = self.hc(
                "read", target, "--lines", str(lines), "--json"
            )
            if result.code != 0 or not isinstance(data, dict):
                raise fail_from(result, "hc read", target)
            return data

        data = fetch()
        waited = False
        if data.get("complete") is False and data.get("why") == "working":
            self.hc(
                "wait",
                target,
                "--timeout",
                str(wait_timeout),
                "--json",
                timeout=wait_timeout + 10,
            )
            waited = True
            data = fetch()
        return {
            "text": data.get("text") or "",
            "complete": data.get("complete"),
            "screen_only": data.get("complete") is False
            and data.get("why") == "working",
            "waited": waited,
            "fallback": None,
        }

    def rows(self, labels):
        args = ["ls", "--json"]
        for label in labels:
            args += ["--label", label]
        data, result = self.hc(*args)
        if result.code != 0 or not isinstance(data, dict):
            raise fail_from(result, "hc ls")
        terminals = data.get("terminals") or []
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(self.row, terminals))

    def row(self, listed):
        target = listed["address"]
        data, result = self.hc("get", target, "--json")
        record = data if result.code == 0 and isinstance(data, dict) else {}
        status = record.get("status") or {}
        labels = record.get("labels") or {}
        kind = agent_kind(status.get("app") or listed.get("agent"))
        dialog = dialog_of(status)
        footer = None
        if kind in FOOTER_MODES and dialog is None and listed.get("state") == "live":
            screen, read = self.hc("read", target, "--lines", "0", "--json")
            if read.code == 0 and isinstance(screen, dict):
                footer = screen.get("text") or ""
        return roster_row(
            address=target,
            name=labels.get("claude.name") or listed.get("name"),
            kind=kind or listed.get("agent"),
            state=listed.get("state"),
            status=status.get("state") or listed.get("status"),
            dialog=dialog,
            footer=footer,
            where=listed.get("where") or labels.get("where"),
            session=labels.get("claude.session"),
            parent=listed.get("parent"),
            cwd=labels.get("claude.cwd") or listed.get("cwd"),
        )

    def create_space(self, name, folder, tab, keep_focus):
        layout = self.layout()
        if layout is None:
            raise Fail(FAILED, "no_window", "the Herdr app window is not open")
        spaces = layout.get("spaces") or []
        clashes = [
            {"id": space.get("id"), "name": space.get("name")}
            for space in spaces
            if (space.get("name") or "").casefold() == name.casefold()
        ]
        if clashes:
            raise Fail(
                SPACE_EXISTS,
                "space_exists",
                f"a space named {name} already exists",
                existing=clashes,
            )
        previous = next((s.get("id") for s in spaces if s.get("active")), None)
        args = ["do", "space.new", "--name", name, "--folder", folder]
        if tab:
            args += ["--tab", tab]
        data, result = self.system.json(["herdr-app", *args])
        if result.code != 0 or (isinstance(data, dict) and "error" in data):
            raise Fail(
                FAILED,
                "space_failed",
                (data or {}).get("error") or error_of(result).get("message"),
            )
        created = next(
            (
                space
                for space in (self.layout() or {}).get("spaces", [])
                if space.get("name") == name
            ),
            {},
        )
        first = (created.get("tabs") or [{}])[0]
        restored = False
        if keep_focus and previous:
            _, back = self.system.json(
                ["herdr-app", "do", "space.select", "--id", previous]
            )
            restored = back.code == 0
        return {
            "backend": "app",
            "space": {"id": created.get("id"), "name": name},
            "tab": {"id": first.get("id"), "name": first.get("name")},
            "focus_restored": restored,
        }

    def layout(self):
        data, result = self.system.json(["herdr-app", "ls"])
        return data if result.code == 0 and isinstance(data, dict) else None

    def seat_from(self, procs, tty):
        terminal = self.system.env("HC_TERMINAL_ID")
        if not terminal:
            return None
        data, result = self.hc("get", terminal, "--json")
        if result.code != 0 or not isinstance(data, dict):
            return None
        proc = procs.get(data.get("pid"))
        if proc is None or proc.tty != tty:
            return None
        return self.describe_seat(terminal, data)

    def describe_seat(self, terminal, record):
        labels = record.get("labels") or {}
        layout = self.layout()
        space, tab = tab_of_terminal(layout, terminal)
        if space is None:
            where = (labels.get("where") or "").split(" / ", 1)
            space = {"id": labels.get("herdr.space"), "name": where[0] or None}
            tab = {
                "id": labels.get("herdr.tab"),
                "name": where[1] if len(where) > 1 else None,
            }
        match, reason = session_comparison(
            self.system,
            labels.get("claude.session"),
            "the terminal has no claude.session label",
        )
        return {
            "backend": "app",
            "target": terminal,
            "terminal": terminal,
            "space": {"id": space.get("id"), "name": space.get("name")},
            "tab": {"id": tab.get("id"), "name": tab.get("name")},
            "session_match": match,
            "session_reason": reason,
            "background_job": None if match is None else not match,
        }


class TuiBackend:
    name = "tui"

    def __init__(self, system):
        self.system = system

    def herdr(self, *args, timeout=30):
        return self.system.json(["herdr", *args], timeout)

    def seat_from(self, procs, tty):
        pane = self.system.env("HERDR_PANE_ID")
        if self.system.env("HERDR_ENV") != "1" or not pane:
            return None
        data, result = self.herdr("pane", "process-info", "--pane", pane)
        info = ((data or {}).get("result") or {}).get("process_info")
        if result.code != 0 or not isinstance(info, dict):
            return None
        shell = procs.get(info.get("shell_pid"))
        found = normalize_tty(info.get("tty")) or (shell.tty if shell else "")
        if found != tty:
            return None
        return self.describe_seat(info.get("pane_id") or pane)

    def describe_seat(self, pane):
        data, _ = self.herdr("pane", "get", pane)
        info = ((data or {}).get("result") or {}).get("pane") or {}
        workspace_id = info.get("workspace_id")
        tab_id = info.get("tab_id")
        workspace = self.label_of("workspace", workspace_id)
        tab = self.label_of("tab", tab_id)
        session = info.get("agent_session") or {}
        recorded = (
            session.get("value")
            if agent_kind(session.get("agent")) == "claude"
            else None
        )
        match, reason = session_comparison(
            self.system, recorded, "the pane has no recorded Claude session"
        )
        return {
            "backend": "tui",
            "target": pane,
            "pane": pane,
            "workspace": {"id": workspace_id, "name": workspace},
            "tab": {"id": tab_id, "name": tab},
            "session_match": match,
            "session_reason": reason,
            "background_job": None if match is None else not match,
        }

    def identity(self, target):
        data, result = self.herdr("agent", "get", target)
        info = ((data or {}).get("result") or {}).get("agent")
        if result.code != 0 or not isinstance(info, dict):
            data, result = self.herdr("pane", "get", target)
            info = ((data or {}).get("result") or {}).get("pane")
        if result.code != 0 or not isinstance(info, dict):
            raise fail_from(result, "herdr agent get", target)
        pane = info.get("pane_id") or target
        process, _ = self.herdr("pane", "process-info", "--pane", pane)
        process = ((process or {}).get("result") or {}).get("process_info") or {}
        session = info.get("agent_session") or {}
        workspace = self.label_of("workspace", info.get("workspace_id"))
        tab = self.label_of("tab", info.get("tab_id"))
        return {
            "target": pane,
            "agent": agent_kind(info.get("agent")),
            "name": info.get("name"),
            "state": "live",
            "status": info.get("agent_status"),
            "dialog": None,
            "labels": {},
            "cwd": info.get("cwd"),
            "parent": None,
            "where": " / ".join(part for part in (workspace, tab) if part) or None,
            "root_pid": process.get("shell_pid"),
            "session": session.get("value"),
            "session_source": "herdr",
            "model": None,
            "effort": None,
            "terminal_args": [],
        }

    def read(self, target, lines, wait_timeout):
        attempts = [("recent-unwrapped", None), ("visible", "visible")]
        if lines == 0:
            attempts = [("visible", None)]
        for source, fallback in attempts:
            args = ["--source", source] + (["--lines", str(lines)] if lines else [])
            data, result = self.herdr("agent", "read", target, *args)
            if result.code == 0 or error_of(result).get("code") != "agent_not_idle":
                break
        if result.code != 0:
            data, pane = self.herdr("pane", "read", target, *args)
            if pane.code != 0:
                raise fail_from(result, "herdr agent read", target)
        read = ((data or {}).get("result") or {}).get("read") or {}
        return {
            "text": read.get("text") or "",
            "complete": not read.get("truncated"),
            "screen_only": fallback == "visible",
            "waited": False,
            "fallback": fallback,
        }

    def listing(self, noun, key, *args):
        data, result = self.herdr(noun, "list", *args)
        if result.code != 0:
            raise fail_from(result, f"herdr {noun} list")
        return ((data or {}).get("result") or {}).get(key) or []

    def rows(self, labels):
        if labels:
            raise Fail(
                USAGE,
                "usage",
                "labels exist only in the Herdr app; the TUI has none to filter by",
            )
        names = {
            agent.get("pane_id"): agent.get("name")
            for agent in self.listing("agent", "agents")
        }
        workspaces = {
            item["workspace_id"]: item.get("label")
            for item in self.listing("workspace", "workspaces")
        }
        tabs = {item["tab_id"]: item.get("label") for item in self.listing("tab", "tabs")}
        panes = self.listing("pane", "panes")
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(
                pool.map(lambda pane: self.row(pane, names, workspaces, tabs), panes)
            )

    def row(self, pane, names, workspaces, tabs):
        target = pane["pane_id"]
        kind = agent_kind(pane.get("agent"))
        status = pane.get("agent_status")
        screen = ""
        if kind in FOOTER_MODES or status == "blocked":
            data, result = self.herdr("pane", "read", target, "--source", "visible")
            if result.code == 0:
                screen = (((data or {}).get("result") or {}).get("read") or {}).get(
                    "text"
                ) or ""
        dialog = None
        if status == "blocked":
            dialog = {"kind": None, "msg": "\n".join(non_blank(screen)[-FOOTER_LINES:])}
        session = pane.get("agent_session") or {}
        return roster_row(
            address=target,
            name=names.get(target),
            kind=kind,
            state="live",
            status=status,
            dialog=dialog,
            footer=screen if kind in FOOTER_MODES and dialog is None else None,
            where=" / ".join(
                part
                for part in (
                    workspaces.get(pane.get("workspace_id")),
                    tabs.get(pane.get("tab_id")),
                )
                if part
            )
            or None,
            session=session.get("value") if kind == agent_kind(session.get("agent")) else None,
            parent=None,
            cwd=pane.get("cwd"),
        )

    def create_space(self, name, folder, tab, keep_focus):
        existing = [
            {"id": item.get("workspace_id"), "name": item.get("label")}
            for item in self.listing("workspace", "workspaces")
            if (item.get("label") or "").casefold() == name.casefold()
        ]
        if existing:
            raise Fail(
                SPACE_EXISTS,
                "space_exists",
                f"a workspace named {name} already exists",
                existing=existing,
            )
        data, result = self.herdr(
            "workspace",
            "create",
            "--label",
            name,
            "--cwd",
            folder,
            "--no-focus" if keep_focus else "--focus",
        )
        found = (data or {}).get("result") or {}
        workspace, first = found.get("workspace"), found.get("tab")
        if result.code != 0 or not workspace or not first:
            raise fail_from(result, "herdr workspace create")
        if tab:
            _, renamed = self.herdr("tab", "rename", first["tab_id"], tab)
            if renamed.code != 0:
                raise fail_from(renamed, "herdr tab rename", first["tab_id"])
        return {
            "backend": "tui",
            "space": {"id": workspace.get("workspace_id"), "name": name},
            "tab": {"id": first.get("tab_id"), "name": tab or first.get("label")},
            "focus_restored": keep_focus,
        }

    def label_of(self, noun, identifier):
        if not identifier:
            return None
        data, _ = self.herdr(noun, "get", identifier)
        item = ((data or {}).get("result") or {}).get(noun) or {}
        return item.get("label")


def dialog_of(status):
    if status.get("state") != "blocked":
        return None
    return {"kind": status.get("kind"), "msg": status.get("msg")}


def command_tokens(args):
    try:
        return shlex.split(args)
    except ValueError:
        return args.split()


def runs_agent(tokens, kind):
    if not tokens:
        return False
    executable = os.path.basename(tokens[0])
    if executable == kind:
        return True
    return (
        executable in ("node", "bun", "deno")
        and len(tokens) > 1
        and os.path.basename(tokens[1]) == kind
    )


def flag_value(tokens, *names):
    for index, token in enumerate(tokens):
        if token in names and index + 1 < len(tokens):
            return tokens[index + 1]
        for name in names:
            if token.startswith(name + "="):
                return token[len(name) + 1 :]
    return None


def find_agent_process(procs, root, kinds):
    for proc in descendants(procs, root):
        tokens = command_tokens(proc.args)
        for kind in kinds:
            if runs_agent(tokens, kind):
                return kind, proc, tokens
    return None, None, []


def codex_effort(tokens):
    for token in tokens:
        match = re.match(r"^model_reasoning_effort=[\"']?(\w+)", token)
        if match:
            return match.group(1)
    return None


def argv_session(kind, tokens):
    if kind == "claude":
        return flag_value(tokens, "--resume", "-r", "--session-id")
    if "resume" in tokens[:-1]:
        return tokens[tokens.index("resume") + 1]
    return None


def read_json_file(path):
    try:
        return parse_json(Path(path).read_text())
    except OSError:
        return None


def transcript_of(system, kind, session):
    if not session:
        return None
    if kind == "claude":
        pattern, base = f"*/{session}.jsonl", system.home / ".claude" / "projects"
    elif kind == "codex":
        pattern, base = f"**/*{session}*.jsonl", system.home / ".codex" / "sessions"
    else:
        return None
    found = sorted(base.glob(pattern)) if base.is_dir() else []
    return str(found[0]) if found else None


DEFAULT_PERMISSION = {
    "claude": ["--permission-mode", "bypassPermissions"],
    "codex": ["--dangerously-bypass-approvals-and-sandbox", "--no-daemon"],
}


def resume_command(kind, session, model, effort, permission):
    if not session or kind not in DEFAULT_PERMISSION:
        return None
    flags = shlex.split(permission) if permission else DEFAULT_PERMISSION[kind]
    if kind == "claude":
        command = ["claude", "--resume", session, *flags]
        command += ["--model", model] if model else []
        command += ["--effort", effort] if effort else []
    else:
        command = ["codex", "resume", session, *flags]
        command += ["--model", model] if model else []
        command += ["-c", f'model_reasoning_effort="{effort}"'] if effort else []
    return shlex.join(command)


def cmd_whois(system, args):
    backend = pick_backend(system, args)
    who = backend.identity(args.target)
    degraded = []
    kinds = [who["agent"]] if who["agent"] in DEFAULT_PERMISSION else list(
        DEFAULT_PERMISSION
    )
    kind, proc, tokens = None, None, []
    if who["root_pid"]:
        kind, proc, tokens = find_agent_process(
            process_table(system), who["root_pid"], kinds
        )
    kind = kind or who["agent"]
    session, source = who["session"], who["session_source"]
    name, cwd = who["name"], who["cwd"]
    if proc is not None and kind == "claude":
        recorded = read_json_file(
            system.home / ".claude" / "sessions" / f"{proc.pid}.json"
        )
        if isinstance(recorded, dict):
            if not session:
                session, source = recorded.get("sessionId"), "sessions-file"
            name = name or recorded.get("name")
            cwd = cwd or recorded.get("cwd")
    if not session and proc is not None:
        session, source = argv_session(kind, tokens), "argv"
    if not who["session"]:
        degraded.append(
            f"no session on the terminal; session read from {source}"
            if session
            else "no session on the terminal, and none found in its process tree"
        )
    if not session:
        source = None
    model = who["model"] or flag_value(tokens, "--model", "-m")
    effort = who["effort"] or (
        flag_value(tokens, "--effort") if kind == "claude" else codex_effort(tokens)
    )
    command = resume_command(kind, session, model, effort, args.permission_flag)
    return {
        "target": who["target"],
        "kind": kind,
        "name": name,
        "state": who["state"],
        "status": who["status"],
        "dialog": who["dialog"],
        "session": session,
        "session_source": source,
        "transcript": transcript_of(system, kind, session),
        "model": model,
        "effort": effort,
        "cwd": cwd,
        "parent": who["parent"],
        "where": who["where"],
        "labels": who["labels"],
        "agent_pid": proc.pid if proc else None,
        "resume": {"cwd": cwd, "command": command} if command else None,
        "degraded": degraded,
    }


FOOTER_MODES = {
    "claude": [
        ("bypass", re.compile(r"bypass permissions on")),
        ("auto", re.compile(r"auto mode on")),
        ("accept-edits", re.compile(r"accept edits on")),
        ("plan", re.compile(r"plan mode on")),
    ],
    "codex": [],
}


def permission_mode(kind, footer):
    for mode, pattern in FOOTER_MODES.get(kind, []):
        if pattern.search(footer):
            return mode
    return None


def roster_row(footer, **row):
    mode = permission_mode(row["kind"], footer) if footer is not None else None
    bypass = None
    if row["kind"] == "claude" and footer is not None:
        bypass = mode == "bypass"
    return {**row, "bypass": bypass, "permission_mode": mode}


def cmd_roster(system, args):
    rows = pick_backend(system, args).rows(args.label)
    return {"count": len(rows), "terminals": rows}


def cmd_space(system, args):
    backend = pick_backend(system, args)
    folder = args.folder or os.getcwd()
    return backend.create_space(args.name, folder, args.tab, args.keep_focus)


def tmux_seat(system, tty):
    pane = system.env("TMUX_PANE")
    if not pane:
        return None
    result = system.run(
        ["tmux", "display-message", "-p", "-t", pane, "#{pane_tty}"]
    )
    if result.code != 0 or normalize_tty(result.out) != tty:
        return None
    return {"backend": "tmux", "target": pane, "pane": pane}


def find_seat(system):
    procs = process_table(system)
    tty = controlling_tty(procs, system.pid)
    if not tty:
        return {
            "backend": "none",
            "reason": "no process up the tree has a controlling terminal",
        }
    for probe in (
        lambda: tmux_seat(system, tty),
        lambda: AppBackend(system).seat_from(procs, tty),
        lambda: TuiBackend(system).seat_from(procs, tty),
    ):
        seat = probe()
        if seat:
            return {**seat, "tty": tty}
    return {
        "backend": "none",
        "tty": tty,
        "reason": "no tmux pane, Herdr app terminal or Herdr TUI pane owns the "
        "controlling terminal",
    }


def cmd_seat(system, args):
    seat = find_seat(system)
    if seat["backend"] == "none":
        raise Fail(NO_SEAT, "no_seat", seat["reason"], **{
            k: v for k, v in seat.items() if k not in ("reason", "backend")
        })
    return seat


def non_blank(text):
    return [line for line in text.splitlines() if line.strip()]


FOOTER_LINES = 5


def cmd_read(system, args):
    backend = pick_backend(system, args)
    lines = 0 if args.footer else args.lines
    result = backend.read(args.target, lines, args.wait_timeout)
    text = result.pop("text").rstrip("\n")
    if args.footer:
        text = "\n".join(non_blank(text)[-FOOTER_LINES:])
    elif args.tail:
        text = "\n".join(non_blank(text)[-args.tail :])
    return {"target": args.target, "text": text, **result}


def pick_backend(system, args):
    if args.backend:
        return {"app": AppBackend, "tui": TuiBackend}[args.backend](system)
    seat = find_seat(system)
    if seat["backend"] not in ("app", "tui"):
        raise Fail(
            NO_SEAT,
            "no_seat",
            seat.get("reason")
            or f"the seat is {seat['backend']}, which has no Herdr backend",
        )
    return {"app": AppBackend, "tui": TuiBackend}[seat["backend"]](system)


COMMANDS = {
    "seat": cmd_seat,
    "whois": cmd_whois,
    "read": cmd_read,
    "roster": cmd_roster,
    "space": cmd_space,
}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        emit({"ok": False, "error": "usage", "reason": message})
        raise SystemExit(USAGE)


def build_parser():
    parser = Parser(prog="herdr.py", description="Drive Herdr from an agent.")
    parser.add_argument("--backend", choices=["app", "tui"])
    sub = parser.add_subparsers(dest="verb", required=True, parser_class=Parser)
    sub.add_parser("seat", help="find the terminal that holds this process")
    whois = sub.add_parser("whois", help="identify the agent in a terminal")
    whois.add_argument("target")
    whois.add_argument("--permission-flag")
    read = sub.add_parser("read", help="print a terminal's screen and history")
    read.add_argument("target")
    read.add_argument("--lines", type=int, default=400)
    read.add_argument("--tail", type=int)
    read.add_argument("--footer", action="store_true")
    read.add_argument("--wait-timeout", type=int, default=30)
    roster = sub.add_parser("roster", help="list every terminal and its state")
    roster.add_argument("--label", action="append", default=[], metavar="K=V")
    space = sub.add_parser("space", help="make a space (app) or workspace (TUI)")
    space.add_argument("name")
    space.add_argument("--folder")
    space.add_argument("--tab")
    space.add_argument("--keep-focus", action="store_true")
    return parser


def emit(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run(argv, system=None):
    system = system or System()
    args = build_parser().parse_args(argv)
    try:
        payload = COMMANDS[args.verb](system, args)
    except Fail as failure:
        emit(
            {
                "ok": False,
                "verb": args.verb,
                "error": failure.error,
                "reason": failure.reason,
                **failure.extra,
            }
        )
        return failure.code
    emit({"ok": True, "verb": args.verb, **payload})
    return OK


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
