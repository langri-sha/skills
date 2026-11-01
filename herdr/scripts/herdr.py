#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import namedtuple
from dataclasses import dataclass
from pathlib import Path

OK = 0
FAILED = 1
USAGE = 2
NOT_FOUND = 3
NO_SEAT = 4

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

    def label_of(self, noun, identifier):
        if not identifier:
            return None
        data, _ = self.herdr(noun, "get", identifier)
        item = ((data or {}).get("result") or {}).get(noun) or {}
        return item.get("label")


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


COMMANDS = {"seat": cmd_seat}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        emit({"ok": False, "error": "usage", "reason": message})
        raise SystemExit(USAGE)


def build_parser():
    parser = Parser(prog="herdr.py", description="Drive Herdr from an agent.")
    sub = parser.add_subparsers(dest="verb", required=True, parser_class=Parser)
    sub.add_parser("seat", help="find the terminal that holds this process")
    return parser


def emit(payload):
    sys.stdout.write(json.dumps(payload, sort_keys=False) + "\n")


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
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
