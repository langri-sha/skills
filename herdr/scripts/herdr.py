#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
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
LAUNCH_FAILED = 6
TIMEOUT = 7
WRONG_STATE = 8
BLOCKED = 9
UNCONFIRMED = 10
FINISHED = 11
NOT_OWNED = 12
HELD = 13

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
    def __init__(
        self,
        runner=None,
        environ=None,
        pid=None,
        home=None,
        clock=None,
        which=None,
        kill=None,
    ):
        self.kill = kill or os.kill
        self.runner = runner or subprocess_runner
        self.now = clock or time.monotonic
        self.which = which or shutil.which
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


def find_space_and_tab(layout, space_query, tab_query):
    space = next(
        (
            s
            for s in (layout.get("spaces") or [])
            if space_query in (s.get("id"), s.get("name"))
        ),
        None,
    )
    tab = next(
        (
            t
            for t in (space or {}).get("tabs") or []
            if tab_query and tab_query in (t.get("id"), t.get("name"))
        ),
        None,
    )
    return space, tab


def screen_dialog(screen):
    return {"kind": None, "msg": "\n".join(non_blank(screen)[-FOOTER_LINES:])}


def until(system, check, seconds, pace):
    deadline = system.now() + seconds
    while True:
        found = check()
        if found:
            return found
        if system.now() >= deadline:
            return None
        pace()


def pane_of_terminal(layout, terminal):
    for space in (layout or {}).get("spaces", []):
        for tab in space.get("tabs", []):
            for found in tab.get("terminals", []):
                if found.get("terminal") == terminal:
                    return found.get("pane")
    return None


SUGGESTION = re.compile(r'^Try\s+["“][^"“”]*["”]$')


def agent_input_text(screen):
    lines = screen.splitlines()
    prompts = [i for i, line in enumerate(lines) if re.match(r"^\s*❯", line)]
    if not prompts:
        return False
    at = prompts[-1]
    typed = lines[at].split("❯", 1)[1].strip()
    if typed and not SUGGESTION.match(typed):
        return True
    continued = False
    for line in lines[at + 1 :]:
        if re.match(r"^\s*─{3,}", line):
            return continued
        continued = continued or bool(line.strip())
    return False


def check_input_box(backend, who, target, only_when_idle):
    idle = who["status"] in ("idle", "done")
    if who["kind"] != "claude" or (only_when_idle and not idle):
        return
    if agent_input_text(backend.screen(target)):
        raise Fail(
            HELD,
            "held_input",
            "text is typed in the agent's input box, so it is left alone",
            target=target,
        )


PROMPT_END = re.compile(r"[$#%>❯›](?=\s)")


def prompt_has_text(screen):
    lines = non_blank(screen)
    if not lines:
        return False
    ends = list(PROMPT_END.finditer(lines[-1]))
    return bool(ends) and bool(lines[-1][ends[-1].end() :].strip())


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

    def shell_for_launch(self, target):
        record = self.record(target)
        if record.get("state") == "finished":
            raise Fail(FINISHED, "finished", f"{target} has ended", target=target)
        idle, why = shell_is_idle(process_table(self.system), record.get("pid"))
        if not idle:
            raise Fail(WRONG_STATE, "not_idle_shell", why, target=target)
        if record.get("reported"):
            raise Fail(
                WRONG_STATE,
                "reported_shell",
                "the terminal once reported an agent status, so hc would wrap "
                "the typed line in hc tags that bash cannot run; launch into a "
                "new terminal instead",
                target=target,
            )

    def screen(self, target):
        data, result = self.hc("read", target, "--lines", "0", "--json")
        if result.code != 0 or not isinstance(data, dict):
            return ""
        return data.get("text") or ""

    def type_line(self, target, line):
        _, result = self.hc("send", target, line, "--json")
        if result.code != 0:
            raise fail_from(result, "hc send", target)

    def observe(self, target):
        record = self.record(target)
        status = record.get("status") or {}
        idle, _ = shell_is_idle(process_table(self.system), record.get("pid"))
        return Observation(
            state=record.get("state"),
            status=status.get("state"),
            dialog=dialog_of(status),
            screen=self.screen(target),
            shell_idle=idle,
        )

    def pace(self, target, needle, seconds):
        args = ["wait", target, "--timeout", str(seconds), "--json"]
        args += ["--output", needle or PACE_SENTINEL]
        self.hc(*args, timeout=seconds + 10)

    def place(self, args):
        layout = self.layout()
        if layout is None:
            raise Fail(FAILED, "no_window", "the Herdr app window is not open")
        tab_name = args.tab
        if args.worker_of:
            labels = self.record(args.worker_of).get("labels") or {}
            query = labels.get("herdr.space")
            tab_name = tab_name or "Worker"
            if not query:
                raise Fail(
                    NOT_FOUND,
                    "no_space",
                    f"{args.worker_of} has no herdr.space label",
                    target=args.worker_of,
                )
        else:
            query = args.space
        space, tab = find_space_and_tab(layout, query, tab_name)
        if space is None:
            raise Fail(NOT_FOUND, "no_space", f"no space {query}", target=query)
        labels = [f"herdr.space={space['id']}"]
        if tab:
            labels.append(f"herdr.tab={tab['id']}")
        return {
            "space": {"id": space["id"], "name": space.get("name")},
            "tab": {"id": tab["id"], "name": tab.get("name")} if tab else None,
            "new_tab_name": None if tab else tab_name,
            "labels": labels,
        }

    def spawn(self, argv, name, cwd, parent, labels):
        args = ["run", "--bg", "--no-notify", "--keep", "--json"]
        args += ["--name", name] if name else []
        args += ["--cwd", cwd] if cwd else []
        args += ["--parent", parent, "--outlive-parent"] if parent else ["--no-parent"]
        for label in labels:
            args += ["--label", label]
        shell = self.system.which("bash") or "/usr/bin/bash"
        args += ["--", shell, "-ic", '"$@"; exec "$0" -i', shell, *argv]
        data, result = self.hc(*args)
        if result.code != 0 or not isinstance(data, dict) or not data.get("address"):
            raise fail_from(result, "hc run")
        return data["address"]

    def adopt(self, address, placement):
        found = until(
            self.system,
            lambda: tab_of_terminal(self.layout(), address)[1],
            10,
            lambda: self.hc("wait", address, "--timeout", "2", "--json", timeout=12),
        )
        tab = placement["tab"]
        if found and placement["new_tab_name"]:
            self.system.json(
                [
                    "herdr-app",
                    "do",
                    "tab.rename",
                    "--id",
                    found["id"],
                    "--name",
                    placement["new_tab_name"],
                ]
            )
        if found:
            tab = {
                "id": found["id"],
                "name": placement["new_tab_name"] or found.get("name"),
            }
        return {"space": placement["space"], "tab": tab}

    def deliver(self, target, text):
        record = self.record(target)
        if record.get("state") == "finished":
            raise Fail(FINISHED, "finished", f"{target} has ended", target=target)
        status = record.get("status") or {}
        if status.get("state") == "blocked":
            raise self.blocked(target, status)
        data, result = self.hc("send", target, text, "--json")
        if result.code == 9:
            raise self.blocked(target, (self.record(target).get("status") or {}))
        if result.code != 0 or not isinstance(data, dict):
            raise fail_from(result, "hc send", target)
        turn = data.get("turn") or 0
        if data.get("started") is not True:
            raise self.unconfirmed(target, data)
        for attempt in range(2):
            now = self.record(target)
            state = (now.get("status") or {}).get("state")
            if state == "working" or (now.get("turn") or 0) > turn:
                return {
                    "target": target,
                    "started": True,
                    "status": state,
                    "turn": now.get("turn"),
                    "confirmed": "working" if state == "working" else "turn",
                }
            if attempt == 0:
                self.hc("wait", target, "--timeout", "15", "--json", timeout=25)
        raise self.unconfirmed(target, data)

    def blocked(self, target, status):
        return Fail(
            BLOCKED,
            "blocked",
            "the terminal is waiting on a dialog; nothing was sent",
            target=target,
            dialog=open_dialog(dialog_of(status) or {}, self.screen(target)),
        )

    def unconfirmed(self, target, sent):
        return Fail(
            UNCONFIRMED,
            "unconfirmed",
            "the text was sent but the agent did not start working; it may still "
            "have arrived, so read the screen before sending again",
            target=target,
            started=sent.get("started"),
            status_at_send=sent.get("status"),
            screen=non_blank(self.screen(target))[-SCREEN_TAIL:],
        )

    def dialog_state(self, target):
        record = self.record(target)
        return dialog_of(record.get("status") or {}), self.screen(target)

    def status_of(self, target):
        return (self.record(target).get("status") or {}).get("state")

    def press(self, target, keys):
        _, result = self.hc("keys", target, *keys, "--json")
        if result.code != 0:
            raise fail_from(result, "hc keys", target)

    def facts(self, target):
        record = self.record(target)
        return {
            "pid": record.get("pid"),
            "keep": bool(record.get("keep")),
            "reported": bool(record.get("reported")),
            "state": record.get("state"),
        }

    def settle(self, target, seconds):
        self.hc("wait", target, "--timeout", str(seconds), "--json", timeout=seconds + 10)

    def focused(self, target):
        status, result = self.system.json(["herdr-app", "status"])
        pane = (status or {}).get("focused_pane") if result.code == 0 else None
        found = pane_of_terminal(self.layout(), target) if pane else None
        return bool(pane) and pane == found

    def check_replaceable(self, target):
        facts = self.facts(target)
        if facts["reported"] and not facts["keep"]:
            raise Fail(
                WRONG_STATE,
                "not_kept",
                "the terminal is not kept, so replacing its shell would end it",
                target=target,
            )
        if self.focused(target):
            raise Fail(
                HELD,
                "held_focus",
                "the terminal has the user's focus, so its shell is left alone",
                target=target,
            )

    def fresh_shell(self, target):
        facts = self.facts(target)
        pid = facts["pid"]
        if not facts["reported"]:
            return False
        idle, why = shell_is_idle(process_table(self.system), pid)
        if not idle:
            raise Fail(WRONG_STATE, "shell_busy", why, target=target)
        self.system.kill(pid, signal.SIGKILL)

        def returned():
            now = self.facts(target)
            return bool(now["pid"]) and now["pid"] != pid and not now["reported"]

        if not until(self.system, returned, 20, lambda: self.pace(target, None, 2)):
            raise Fail(
                TIMEOUT,
                "shell_did_not_return",
                "the shell did not come back after the kill",
                target=target,
            )
        return True

    def parent_of(self, target):
        return self.record(target).get("parent")

    def discard(self, target):
        _, killed = self.hc("kill", target, "--json")
        if killed.code != 0:
            raise fail_from(killed, "hc kill", target)
        self.hc("wait", target, "--timeout", "5", "--json", timeout=15)
        _, removed = self.hc("rm", target, "--json")
        if removed.code != 0:
            raise fail_from(removed, "hc rm", target)

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
            dialog = screen_dialog(screen)
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

    def shell_for_launch(self, target):
        data, result = self.herdr("pane", "process-info", "--pane", target)
        info = ((data or {}).get("result") or {}).get("process_info")
        if result.code != 0 or not isinstance(info, dict):
            raise fail_from(result, "herdr pane process-info", target)
        idle, why = shell_is_idle(process_table(self.system), info.get("shell_pid"))
        if not idle:
            raise Fail(WRONG_STATE, "not_idle_shell", why, target=target)

    def type_line(self, target, line):
        _, result = self.herdr("pane", "run", target, line)
        if result.code != 0:
            raise fail_from(result, "herdr pane run", target)

    def screen(self, target, via="pane"):
        data, result = self.herdr(via, "read", target, "--source", "visible")
        read = ((data or {}).get("result") or {}).get("read") or {}
        return read.get("text") or "" if result.code == 0 else ""

    def observe(self, target):
        data, result = self.herdr("pane", "get", target)
        info = ((data or {}).get("result") or {}).get("pane")
        if result.code != 0 or not isinstance(info, dict):
            raise fail_from(result, "herdr pane get", target)
        status = info.get("agent_status")
        status = status if status in ("idle", "working", "blocked", "done") else None
        screen = self.screen(target)
        process, _ = self.herdr("pane", "process-info", "--pane", target)
        process = ((process or {}).get("result") or {}).get("process_info") or {}
        idle, _ = shell_is_idle(process_table(self.system), process.get("shell_pid"))
        dialog = None
        if status == "blocked":
            dialog = screen_dialog(screen)
        return Observation("live", status, dialog, screen, idle)

    def pace(self, target, needle, seconds):
        self.herdr(
            "pane",
            "wait-output",
            target,
            "--match",
            needle or PACE_SENTINEL,
            "--timeout",
            str(seconds * 1000),
            timeout=seconds + 10,
        )

    def deliver(self, target, text):
        data, result = self.herdr("agent", "prompt", target, text)
        code = error_of(result).get("code")
        if code == "agent_blocked":
            screen = self.screen(target, "agent")
            raise Fail(
                BLOCKED,
                "blocked",
                "the agent is waiting on a dialog; nothing was sent",
                target=target,
                dialog=open_dialog(screen_dialog(screen), screen),
            )
        if code == "agent_prompt_stalled":
            raise Fail(
                UNCONFIRMED,
                "unconfirmed",
                "herdr saw no change after the prompt; it may still have arrived, "
                "so read the screen before sending again",
                target=target,
                screen=non_blank(self.screen(target, "agent"))[-SCREEN_TAIL:],
            )
        if result.code != 0:
            raise fail_from(result, "herdr agent prompt", target)
        agent = ((data or {}).get("result") or {}).get("agent") or {}
        return {
            "target": target,
            "started": True,
            "status": agent.get("agent_status"),
            "turn": None,
            "confirmed": "herdr",
        }


    def dialog_state(self, target):
        status = self.status_of(target)
        screen = self.screen(target, "agent")
        if status != "blocked":
            return None, screen
        return screen_dialog(screen), screen

    def status_of(self, target):
        data, result = self.herdr("agent", "get", target)
        agent = ((data or {}).get("result") or {}).get("agent")
        if result.code != 0 or not isinstance(agent, dict):
            raise fail_from(result, "herdr agent get", target)
        return agent.get("agent_status")

    def press(self, target, keys):
        _, result = self.herdr("agent", "send-keys", target, *keys)
        if result.code != 0:
            raise fail_from(result, "herdr agent send-keys", target)

    def facts(self, target):
        data, result = self.herdr("pane", "process-info", "--pane", target)
        info = ((data or {}).get("result") or {}).get("process_info")
        if result.code != 0 or not isinstance(info, dict):
            raise fail_from(result, "herdr pane process-info", target)
        return {
            "pid": info.get("shell_pid"),
            "keep": True,
            "reported": False,
            "state": "live",
        }

    def settle(self, target, seconds):
        self.herdr(
            "agent", "wait", target, "--timeout", str(seconds * 1000), timeout=seconds + 10
        )

    def check_replaceable(self, target):
        data, _ = self.herdr("pane", "get", target)
        pane = ((data or {}).get("result") or {}).get("pane") or {}
        if pane.get("focused"):
            raise Fail(
                HELD,
                "held_focus",
                "the pane has the user's focus, so its shell is left alone",
                target=target,
            )

    def fresh_shell(self, target):
        return False

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
    "codex": ["--dangerously-bypass-approvals-and-sandbox"],
}


def agent_argv(kind, head, permission, model, effort, backend, name=None):
    flags = shlex.split(permission) if permission else DEFAULT_PERMISSION[kind]
    if kind == "claude":
        argv = ["claude", *head, *flags]
        argv += ["--model", model] if model else []
        argv += ["--effort", effort] if effort else []
        argv += ["--name", name] if name else []
        return argv
    argv = ["codex", *head] + (["--no-daemon"] if backend == "app" else []) + flags
    argv += ["--model", model] if model else []
    argv += ["-c", f'model_reasoning_effort="{effort}"'] if effort else []
    return argv


def resume_command(kind, session, model, effort, permission, backend):
    if not session or kind not in DEFAULT_PERMISSION:
        return None
    head = ["--resume", session] if kind == "claude" else ["resume", session]
    argv = agent_argv(kind, head, permission, model, effort, backend)
    return shlex.join(argv)


def cmd_whois(system, args):
    backend = pick_backend(system, args)
    return whois_report(system, backend, args.target, args.permission_flag)


def whois_report(system, backend, target, permission_flag):
    who = backend.identity(target)
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
    command = resume_command(
        kind, session, model, effort, permission_flag, backend.name
    )
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


@dataclass(frozen=True)
class Observation:
    state: str
    status: str
    dialog: dict
    screen: str
    shell_idle: bool


SHELLS = {"bash", "zsh", "fish", "sh", "dash"}
SLICE_SECONDS = 5
PACE_SENTINEL = "herdr-pace-sentinel"
SCREEN_TAIL = 12
LAUNCH_FAILURES = (
    r"authorization prompt dismissed",
    r"authorization timeout",
    r"connecting to desktop app timed out",
)
MODE_OF_FLAG = {
    "bypassPermissions": "bypass",
    "acceptEdits": "accept-edits",
    "plan": "plan",
    "auto": "auto",
}
AGENT_NAME = re.compile(r"^[a-z0-9_-]{1,32}$")
OPTION_LINE = re.compile(r"^\s*([❯>›]?)\s*(\d+)[.)]\s+(.+?)\s*$")


def shell_is_idle(procs, root):
    proc = procs.get(root)
    if proc is None:
        return False, "the terminal's process is gone"
    tokens = command_tokens(proc.args)
    executable = os.path.basename(tokens[0]).lstrip("-") if tokens else ""
    if executable not in SHELLS:
        return False, f"the terminal runs {executable or 'something'}, not a shell"
    busy = descendants(procs, root)[1:]
    if busy:
        running = os.path.basename(command_tokens(busy[0].args)[0])
        return False, f"the shell is running {running}"
    return True, ""


def expected_mode(kind, permission):
    if kind != "claude":
        return None
    flags = shlex.split(permission) if permission else DEFAULT_PERMISSION[kind]
    if "--dangerously-skip-permissions" in flags:
        return "bypass"
    return MODE_OF_FLAG.get(flag_value(flags, "--permission-mode"))


def model_shown(model, screen):
    if not model:
        return True
    lowered = screen.lower()
    family = model.lower().removeprefix("claude-").split("-")[0]
    return model.lower() in lowered or family in lowered


def matching_lines(pattern, screen):
    return [
        line for line in screen.splitlines() if re.search(pattern, line, re.IGNORECASE)
    ]


def failure_hit(patterns, screen, baseline):
    for pattern in patterns:
        found = matching_lines(pattern, screen)
        if len(found) > baseline.get(pattern, 0):
            return found[-1].strip()
    return None


def failure_counts(patterns, screen):
    return {pattern: len(matching_lines(pattern, screen)) for pattern in patterns}


DIALOG_CONTEXT = 6
DIALOG_AFTER = 2


def option_run(screen):
    lines = non_blank(screen)
    runs, current = [], []
    for index, line in enumerate(lines):
        if OPTION_LINE.match(line):
            current.append(index)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return lines, (runs[-1] if runs else [])


def dialog_block(screen):
    lines, run = option_run(screen)
    if not run:
        return lines[-FOOTER_LINES:]
    return lines[max(0, run[0] - DIALOG_CONTEXT) : run[-1] + 1 + DIALOG_AFTER]


def dialog_options(msg, screen):
    lines, run = option_run(screen)
    numbered = [OPTION_LINE.match(lines[index]) for index in run]
    if numbered:
        return [
            {"number": int(m.group(2)), "label": m.group(3), "selected": bool(m.group(1))}
            for m in numbered
        ]
    tail = re.search(r"\(([^()]+)\)\s*$", msg or "")
    if not tail:
        return []
    labels = [part.strip() for part in re.split(r"\s+[·|]\s+|,\s*", tail.group(1))]
    return [
        {"number": None, "label": label, "selected": index == 0}
        for index, label in enumerate(labels)
        if label
    ]


def open_dialog(dialog, screen):
    options = dialog_options(dialog.get("msg"), screen)
    return {
        "kind": dialog.get("kind"),
        "msg": dialog.get("msg"),
        "options": [option["label"] for option in options],
    }


def await_launch(system, backend, address, spec):
    start = system.now()
    deadline = start + spec["timeout"]
    returned = 0
    while True:
        obs = backend.observe(address)
        tail = non_blank(obs.screen)[-SCREEN_TAIL:]
        footer = tail[-FOOTER_LINES:]
        mode = permission_mode(spec["kind"], "\n".join(footer))
        shown = model_shown(spec["model"], obs.screen)
        context = {
            "target": address,
            "status": obs.status,
            "permission_mode": mode,
            "model_shown": shown,
            "footer": footer,
            "elapsed_s": round(system.now() - start),
        }
        if obs.state == "finished":
            raise Fail(
                FINISHED, "finished", "the terminal ended before the agent was ready", **context
            )
        if obs.dialog:
            raise Fail(
                BLOCKED,
                "blocked",
                "the agent opened a dialog",
                dialog=open_dialog(obs.dialog, obs.screen),
                **context,
            )
        hit = failure_hit(spec["patterns"], obs.screen, spec["baseline"])
        if hit:
            raise Fail(LAUNCH_FAILED, "launcher_failed", hit, **context)
        mode_ok = spec["mode"] is None or mode == spec["mode"]
        if obs.status in ("idle", "done") and mode_ok and not obs.shell_idle:
            return context
        returned = returned + 1 if obs.shell_idle else 0
        if returned >= 2:
            raise Fail(
                LAUNCH_FAILED,
                "shell_returned",
                "the shell prompt came back without an agent",
                **context,
            )
        left = deadline - system.now()
        if left <= 0:
            raise Fail(
                TIMEOUT,
                "timeout",
                f"the agent was not ready after {spec['timeout']}s",
                **context,
            )
        backend.pace(address, spec["needle"], max(1, math.ceil(min(left, SLICE_SECONDS))))


def plan_launch(backend, agent, head, model, effort, name, permission, patterns, timeout):
    argv = agent_argv(
        agent,
        head,
        permission,
        model,
        effort,
        backend.name,
        name if agent == "claude" else None,
    )
    mode = expected_mode(agent, permission)
    return {
        "argv": argv,
        "line": shlex.join(argv),
        "spec": {
            "kind": agent,
            "model": model,
            "mode": mode,
            "needle": {"bypass": "bypass permissions on"}.get(mode),
            "patterns": [*LAUNCH_FAILURES, *patterns],
            "timeout": timeout,
            "baseline": {},
        },
    }


def launch_in(system, backend, target, plan, cwd):
    backend.shell_for_launch(target)
    spec = plan["spec"]
    spec["baseline"] = failure_counts(spec["patterns"], backend.screen(target))
    prefix = f"cd {shlex.quote(cwd)} && " if cwd else ""
    backend.type_line(target, prefix + plan["line"])
    return await_launch(system, backend, target, spec)


def launch_result(address, args, plan, ready, placed):
    return {
        "address": address,
        "name": args.name,
        "agent": args.agent,
        "model": args.model,
        "effort": args.effort,
        "command": plan["line"],
        "placed": placed,
        **{k: v for k, v in ready.items() if k != "target"},
    }


def cmd_launch(system, args):
    if args.name and not args.target and not AGENT_NAME.match(args.name):
        raise Fail(USAGE, "usage", "--name is 1-32 of a-z 0-9 - _")
    if not (args.target or args.space or args.worker_of):
        raise Fail(
            USAGE, "usage", "give --in, --space or --worker-of to say where to launch"
        )
    backend = pick_backend(system, args)
    plan = plan_launch(
        backend,
        args.agent,
        [],
        args.model,
        args.effort,
        args.name,
        args.permission_flag,
        args.fail_pattern,
        args.timeout,
    )
    if args.target:
        ready = launch_in(system, backend, args.target, plan, args.cwd)
        return launch_result(args.target, args, plan, ready, None)
    if backend.name != "app":
        raise Fail(
            USAGE,
            "usage",
            "placing a new terminal is app-only; use --in with a TUI pane",
        )
    placement = backend.place(args)
    parent = None if args.no_parent else backend.caller
    address = backend.spawn(
        plan["argv"], args.name, args.cwd, parent, placement["labels"]
    )
    placed = backend.adopt(address, placement)
    ready = await_launch(system, backend, address, plan["spec"])
    return launch_result(address, args, plan, ready, placed)


HANDOFF_REQUEST = (
    "Write a handoff note for the agent that replaces you to {path}: what you "
    "did, what is left, decisions still open, and the files, branches and pull "
    "requests involved. Reply with one line when the file is written."
)
EXIT_KEYS = ["ctrl+c", "ctrl+c"]


def run_handoff(system, backend, target, path, timeout):
    path = Path(path).resolve()
    if path.exists():
        raise Fail(
            WRONG_STATE,
            "handoff_exists",
            f"{path} already exists, so it cannot prove a new handoff",
            target=target,
        )
    backend.deliver(target, HANDOFF_REQUEST.format(path=path))
    deadline = system.now() + timeout
    while True:
        backend.settle(target, max(1, min(30, math.ceil(deadline - system.now()))))
        if path.exists():
            return str(path)
        status = backend.status_of(target)
        if status == "blocked":
            dialog, screen = backend.dialog_state(target)
            raise Fail(
                BLOCKED,
                "blocked",
                "the agent opened a dialog while writing the handoff",
                target=target,
                dialog=open_dialog(dialog or {}, screen),
            )
        if status in ("idle", "done"):
            raise Fail(
                WRONG_STATE,
                "handoff_missing",
                f"the agent stopped without writing {path}",
                target=target,
            )
        if system.now() >= deadline:
            raise Fail(
                TIMEOUT,
                "handoff_timeout",
                f"no handoff at {path} after {timeout}s",
                target=target,
            )


def exit_agent(system, backend, target):
    pressed = False

    def back():
        facts = backend.facts(target)
        return facts["state"] == "finished" or shell_is_idle(
            process_table(system), facts["pid"]
        )[0]

    for _ in range(2):
        if back():
            return pressed
        backend.press(target, EXIT_KEYS)
        pressed = True
        if until(system, back, 15, lambda: backend.pace(target, None, 3)):
            return pressed
    raise Fail(
        TIMEOUT,
        "exit_failed",
        "ctrl+c twice did not bring the shell back",
        target=target,
    )


def cmd_relaunch(system, args):
    backend = pick_backend(system, args)
    who = whois_report(system, backend, args.target, None)
    target = who["target"]
    previous = {
        "kind": who["kind"],
        "session": who["session"],
        "model": who["model"],
        "effort": who["effort"],
        "resume": who["resume"],
    }
    state = {"exited": False}
    try:
        if who["status"] == "blocked":
            raise Fail(
                BLOCKED,
                "blocked",
                "the agent is waiting on a dialog; answer it or ask the user first",
                target=target,
                dialog=open_dialog(who["dialog"], backend.screen(target)),
            )
        agent = args.agent or who["kind"]
        if agent not in DEFAULT_PERMISSION:
            raise Fail(USAGE, "usage", "the terminal runs no known agent; give --agent")
        head = []
        if args.resume:
            if agent != who["kind"] or not who["session"]:
                raise Fail(
                    WRONG_STATE,
                    "no_session",
                    "there is no session of that agent to resume in this terminal",
                    target=target,
                )
            head = (
                ["--resume", who["session"]]
                if agent == "claude"
                else ["resume", who["session"]]
            )
        if who["agent_pid"] is None:
            idle, why = shell_is_idle(process_table(system), backend.facts(target)["pid"])
            if not idle:
                raise Fail(
                    WRONG_STATE,
                    "shell_busy",
                    f"no agent runs in this terminal, and {why}; nothing was pressed",
                    target=target,
                )
        backend.check_replaceable(target)
        check_input_box(backend, who, target, only_when_idle=True)
        handoff = None
        if args.handoff:
            handoff = run_handoff(
                system, backend, target, args.handoff, args.handoff_timeout
            )
            check_input_box(backend, who, target, only_when_idle=False)
        exited = exit_agent(system, backend, target)
        state["exited"] = exited
        backend.check_replaceable(target)
        if not exited and prompt_has_text(backend.screen(target)):
            raise Fail(
                HELD,
                "held_input",
                "text is typed at the shell prompt, so the shell is left alone",
                target=target,
            )
        replaced = backend.fresh_shell(target)
        plan = plan_launch(
            backend,
            agent,
            head,
            args.model or (who["model"] if args.resume else None),
            args.effort or (who["effort"] if args.resume else None),
            args.name,
            args.permission_flag,
            args.fail_pattern,
            args.timeout,
        )
        ready = launch_in(system, backend, target, plan, args.cwd or who["cwd"])
    except Fail as failure:
        failure.extra.update(exited_agent=state["exited"], previous=previous)
        raise
    return {
        "address": target,
        "previous": previous,
        "agent": agent,
        "resumed": bool(args.resume),
        "handoff": handoff,
        "exited_agent": exited,
        "replaced_shell": replaced,
        "command": plan["line"],
        **{k: v for k, v in ready.items() if k != "target"},
    }


def archive_brief(path):
    source = Path(path)
    if not source.is_file():
        raise Fail(NOT_FOUND, "not_found", f"no brief at {path}")
    destination = source.parent / "closed" / source.name
    if destination.exists():
        raise Fail(WRONG_STATE, "brief_archived", f"{destination} already exists")
    return source, destination


def cmd_close(system, args):
    backend = pick_backend(system, args)
    if backend.name != "app":
        raise Fail(
            USAGE,
            "usage",
            "the TUI records no parent, so close cannot tell which panes the caller "
            "started; close them in Herdr",
        )
    caller = backend.caller
    if not caller:
        raise Fail(
            NO_SEAT,
            "no_caller",
            "without a seat close cannot tell which terminals are yours",
        )
    parent = backend.parent_of(args.target)
    if parent != caller:
        raise Fail(
            NOT_OWNED,
            "not_owned",
            f"{args.target} was not started by {caller}, so it is not yours to close",
            target=args.target,
            parent=parent,
        )
    brief = archive_brief(args.brief) if args.brief else None
    exited = exit_agent(system, backend, args.target)
    backend.discard(args.target)
    archived = None
    if brief:
        brief[1].parent.mkdir(exist_ok=True)
        brief[0].rename(brief[1])
        archived = str(brief[1])
    return {
        "target": args.target,
        "exited_agent": exited,
        "removed": True,
        "brief": archived,
    }


def cmd_deliver(system, args):
    if (args.text is None) == (args.file is None):
        raise Fail(USAGE, "usage", "give the text, or --file, but not both")
    text = args.text
    if args.file is not None:
        try:
            text = Path(args.file).read_text()
        except OSError as problem:
            raise Fail(USAGE, "usage", f"cannot read {args.file}: {problem.strerror}")
    if not text.strip():
        raise Fail(USAGE, "usage", "nothing to send")
    return pick_backend(system, args).deliver(args.target, text)


FOLDER_TRUST = re.compile(
    r"do you trust the files in this folder"
    r"|is this a project you created or one you trust"
    r"|trust this folder"
    r"|trust the contents of this directory",
    re.IGNORECASE,
)
TOOL_PERMISSION = re.compile(
    r"bash command|do you want to (proceed|make this edit|create|allow)"
    r"|allow (this|claude|codex)|run this command|wants to (run|edit|read|write)",
    re.IGNORECASE,
)
ALLOWLIST = {"folder-trust": FOLDER_TRUST}


def dialog_class(dialog, screen):
    if dialog.get("kind") == "permission":
        return None
    text = "\n".join([dialog.get("msg") or "", *dialog_block(screen)])
    if TOOL_PERMISSION.search(text):
        return None
    for name, pattern in ALLOWLIST.items():
        if pattern.search(text):
            return name
    return None


def keys_for(options, wanted):
    labels = [option["label"] for option in options]
    index = None
    if wanted.isdigit():
        index = next(
            (i for i, option in enumerate(options) if option["number"] == int(wanted)),
            None,
        )
    if index is None:
        matches = [
            i for i, label in enumerate(labels) if wanted.lower() in label.lower()
        ]
        index = matches[0] if len(matches) == 1 else None
    if index is None:
        raise Fail(
            USAGE, "usage", f"no single option matches {wanted}", options=labels
        )
    current = next((i for i, option in enumerate(options) if option["selected"]), 0)
    move = ["down"] * (index - current) + ["up"] * (current - index)
    return labels[index], [*move, "enter"]


def cmd_dialog(system, args):
    backend = pick_backend(system, args)
    dialog, screen = backend.dialog_state(args.target)
    if dialog is None:
        if args.answer is not None:
            raise Fail(
                WRONG_STATE, "no_dialog", "no dialog is open", target=args.target
            )
        return {"target": args.target, "dialog": None, "answerable": None}
    shown = open_dialog(dialog, screen)
    kind = dialog_class(dialog, screen)
    if args.answer is None:
        return {"target": args.target, "dialog": shown, "answerable": kind}
    if kind is None:
        raise Fail(
            BLOCKED,
            "not_allowed",
            "this dialog is not on the allowlist; ask the user",
            target=args.target,
            dialog=shown,
        )
    label, keys = keys_for(dialog_options(dialog.get("msg"), screen), args.answer)
    backend.press(args.target, keys)
    return {
        "target": args.target,
        "answered": label,
        "dialog_class": kind,
        "keys": keys,
        "status": backend.status_of(args.target),
    }


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
        backend = {"app": AppBackend, "tui": TuiBackend}[args.backend](system)
        backend.caller = None
        return backend
    seat = find_seat(system)
    if seat["backend"] not in ("app", "tui"):
        raise Fail(
            NO_SEAT,
            "no_seat",
            seat.get("reason")
            or f"the seat is {seat['backend']}, which has no Herdr backend",
        )
    backend = {"app": AppBackend, "tui": TuiBackend}[seat["backend"]](system)
    backend.caller = seat["target"]
    return backend


COMMANDS = {
    "seat": cmd_seat,
    "whois": cmd_whois,
    "read": cmd_read,
    "roster": cmd_roster,
    "space": cmd_space,
    "launch": cmd_launch,
    "deliver": cmd_deliver,
    "dialog": cmd_dialog,
    "relaunch": cmd_relaunch,
    "close": cmd_close,
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
    launch = sub.add_parser("launch", help="start an agent and wait until it is ready")
    launch.add_argument("--in", dest="target", metavar="TERMINAL")
    launch.add_argument("--space")
    launch.add_argument("--tab")
    launch.add_argument("--worker-of", metavar="TERMINAL")
    launch.add_argument("--agent", choices=["claude", "codex"], default="claude")
    launch.add_argument("--model")
    launch.add_argument("--effort")
    launch.add_argument("--name")
    launch.add_argument("--cwd")
    launch.add_argument("--no-parent", action="store_true")
    launch.add_argument("--permission-flag")
    launch.add_argument("--fail-pattern", action="append", default=[], metavar="REGEX")
    launch.add_argument("--timeout", type=int, default=180)
    deliver = sub.add_parser("deliver", help="send text to an agent and confirm it started")
    deliver.add_argument("target")
    deliver.add_argument("text", nargs="?")
    deliver.add_argument("--file")
    dialog = sub.add_parser("dialog", help="show a terminal's open dialog, or answer an allowed one")
    dialog.add_argument("target")
    dialog.add_argument("--answer", metavar="OPTION")
    relaunch = sub.add_parser("relaunch", help="swap or resume the agent in a terminal")
    relaunch.add_argument("target")
    relaunch.add_argument("--agent", choices=["claude", "codex"])
    relaunch.add_argument("--model")
    relaunch.add_argument("--effort")
    relaunch.add_argument("--name")
    relaunch.add_argument("--cwd")
    relaunch.add_argument("--resume", action="store_true")
    relaunch.add_argument("--handoff", metavar="PATH")
    relaunch.add_argument("--handoff-timeout", type=int, default=300)
    relaunch.add_argument("--permission-flag")
    relaunch.add_argument("--fail-pattern", action="append", default=[], metavar="REGEX")
    relaunch.add_argument("--timeout", type=int, default=180)
    close = sub.add_parser("close", help="exit and remove a terminal the caller started")
    close.add_argument("target")
    close.add_argument("--brief", metavar="PATH")
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
