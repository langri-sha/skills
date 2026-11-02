import tempfile
import unittest
from pathlib import Path

from support import (
    SESSION_PROCESSES,
    FakeClock,
    FakeRunner,
    failed,
    not_found,
    ok,
    processes,
    run_verb,
)

GET = ("hc", "get", "t7", "--json")
PS = ("ps", "-A", "-o", "pid=,ppid=,tty=,args=")
KEYS = ("hc", "keys", "t7", "ctrl+c", "ctrl+c", "--json")
KILL = ("hc", "kill", "t7", "--json")
REMOVE = ("hc", "rm", "t7", "--json")
AGENT = processes(
    (800, 1, "pts/3", "/usr/bin/bash -i"), (810, 800, "pts/3", "/opt/agents/claude")
)
SHELL = processes((800, 1, "pts/3", "/usr/bin/bash -i"))


def record(parent="t1", state="live", pid=800):
    return ok({"address": "t7", "pid": pid, "parent": parent, "state": state})


def close(responses, *argv):
    waits = {
        ("hc", "wait", "t7", "--timeout", str(n), "--json"): ok({"ended": True})
        for n in range(1, 6)
    }
    pace = {
        ("hc", "wait", "t7", "--timeout", str(n), "--json", "--output", "herdr-pace-sentinel"): ok({"ended": False})
        for n in range(1, 4)
    }
    seat = {
        ("hc", "get", "t1", "--json"): ok({"address": "t1", "pid": 800, "labels": {}}),
        ("herdr-app", "ls"): failed(1, text="no window"),
    }
    tables = responses.get(PS)
    tables = tables if isinstance(tables, list) else [tables] if tables else []
    clock = FakeClock()
    runner = FakeRunner(
        {**pace, **waits, **seat, **responses, PS: [SESSION_PROCESSES, *tables]},
        clock=clock,
    )
    code, out = run_verb(
        ["close", "t7", *argv], runner, {"HC_TERMINAL_ID": "t1"}, clock=clock
    )
    return runner, code, out


class CloseATerminal(unittest.TestCase):
    def test_exits_the_agent_then_kills_and_removes_the_terminal(self):
        runner, code, out = close(
            {GET: record(), PS: [AGENT, SHELL], KEYS: ok({}), KILL: ok({}), REMOVE: ok({})}
        )
        self.assertEqual(code, 0)
        self.assertIs(out["exited_agent"], True)
        self.assertEqual(
            [call[:2] for call in runner.calls if call[0] == "hc" and call[1] in ("keys", "kill", "rm")],
            [("hc", "keys"), ("hc", "kill"), ("hc", "rm")],
        )

    def test_a_shell_without_an_agent_is_just_removed(self):
        runner, code, out = close({GET: record(), PS: SHELL, KILL: ok({}), REMOVE: ok({})})
        self.assertEqual(code, 0)
        self.assertIs(out["exited_agent"], False)
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_refuses_a_terminal_the_caller_did_not_start(self):
        runner, code, out = close({GET: record(parent="t9")})
        self.assertEqual(code, 12)
        self.assertEqual(out["error"], "not_owned")
        self.assertEqual(out["parent"], "t9")
        self.assertEqual(runner.ran("hc", "kill"), [])

    def test_refuses_a_terminal_with_no_parent(self):
        runner, code, _ = close({GET: record(parent=None)})
        self.assertEqual(code, 12)
        self.assertEqual(runner.ran("hc", "kill"), [])

    def test_an_agent_that_will_not_exit_is_left_alone(self):
        runner, code, out = close({GET: record(), PS: AGENT, KEYS: ok({})})
        self.assertEqual(code, 7)
        self.assertEqual(out["error"], "exit_failed")
        self.assertEqual(runner.ran("hc", "kill"), [])

    def test_an_unknown_terminal_exits_three(self):
        _, code, _ = close({GET: not_found()})
        self.assertEqual(code, 3)

    def test_moves_the_brief_to_the_closed_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            brief = Path(folder, "worker.md")
            brief.write_text("brief")
            _, code, out = close(
                {GET: record(), PS: SHELL, KILL: ok({}), REMOVE: ok({})},
                "--brief",
                str(brief),
            )
            self.assertEqual(code, 0)
            self.assertFalse(brief.exists())
            self.assertEqual(Path(folder, "closed", "worker.md").read_text(), "brief")
            self.assertEqual(out["brief"], str(Path(folder, "closed", "worker.md")))

    def test_a_missing_brief_stops_before_anything_is_closed(self):
        runner, code, out = close(
            {GET: record(), PS: SHELL}, "--brief", "/nonexistent/worker.md"
        )
        self.assertEqual(code, 3)
        self.assertEqual(runner.ran("hc", "kill"), [])

    def test_a_failed_removal_is_reported(self):
        gone = failed(1, {"error": {"kind": "busy", "message": "still running"}})
        _, code, out = close({GET: record(), PS: SHELL, KILL: ok({}), REMOVE: gone})
        self.assertEqual(code, 1)
        self.assertEqual(out["reason"], "still running")

    def test_the_tui_cannot_tell_which_panes_are_the_callers(self):
        code, out = run_verb(
            ["--backend", "tui", "close", "w1:p2"], FakeRunner({})
        )
        self.assertEqual(code, 2)

    def test_without_a_seat_close_refuses(self):
        runner = FakeRunner({PS: processes((902, 1, "?", "python3"))})
        code, out = run_verb(["--backend", "app", "close", "t7"], runner)
        self.assertEqual(code, 4)
        self.assertEqual(out["error"], "no_caller")


if __name__ == "__main__":
    unittest.main()
