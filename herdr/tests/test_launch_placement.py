import unittest

from support import (
    PS,
    SESSION_PROCESSES,
    FakeClock,
    FakeRunner,
    agent_status,
    failed,
    ok,
    run_verb,
    screen,
)
from test_launch import PROMPT, READY, SHELL_RUNNING

LAYOUT = {
    "spaces": [
        {
            "id": "sp1",
            "name": "Project",
            "tabs": [
                {"id": "tb1", "name": "Conductor", "terminals": [{"terminal": "t1"}]},
                {"id": "tb2", "name": "Worker", "terminals": [{"terminal": "t2"}]},
            ],
        }
    ]
}
WITH_NEW = {
    "spaces": [
        {
            "id": "sp1",
            "name": "Project",
            "tabs": [
                *LAYOUT["spaces"][0]["tabs"],
                {"id": "tb9", "name": "5", "terminals": [{"terminal": "t9"}]},
            ],
        }
    ]
}
COMMAND = "claude --permission-mode bypassPermissions"
SHELL = "/usr/bin/bash"
RUN = ("hc", "run", "--bg", "--no-notify", "--keep", "--json")


def run_args(labels, name="w1", cwd=None, parent=None):
    args = list(RUN)
    args += ["--name", name]
    args += ["--cwd", cwd] if cwd else []
    args += ["--parent", parent, "--outlive-parent"] if parent else ["--no-parent"]
    for label in labels:
        args += ["--label", label]
    return tuple(args + ["--", SHELL, "-ic", '"$@"; exec "$0" -i', SHELL, *COMMAND.split(), "--name", name])


def record(status, pid=800, labels=None):
    return ok(
        {
            "address": "t9",
            "pid": pid,
            "state": "live",
            "reported": False,
            "labels": labels or {},
            "status": status,
        }
    )


def launched(responses, *argv, layouts=None):
    clock = FakeClock()
    base = {
        ("herdr-app", "ls"): layouts or [ok(LAYOUT)],
        ("hc", "get", "t9", "--json"): [
            record(agent_status("working")),
            record(agent_status("idle")),
        ],
        ("hc", "read", "t9", "--lines", "0", "--json"): [screen(PROMPT), screen(READY)],
        ("ps", "-A", "-o", "pid=,ppid=,tty=,args="): SHELL_RUNNING,
        ("hc", "wait", "t9", "--timeout", "2", "--json"): ok({"ended": False}),
        **{
            ("hc", "wait", "t9", "--timeout", str(n), "--json", "--output", "bypass permissions on"): ok(
                {"ended": False}
            )
            for n in range(1, 6)
        },
    }
    runner = FakeRunner({**base, **responses}, clock=clock)
    code, out = run_verb(
        ["--backend", "app", "launch", *argv], runner, clock=clock
    )
    return runner, code, out


class LaunchIntoANewTerminal(unittest.TestCase):
    def test_places_the_terminal_in_an_existing_tab_by_labels(self):
        run = run_args(["herdr.space=sp1", "herdr.tab=tb2"], cwd="/tmp/repo")
        layouts = [ok(LAYOUT), ok(LAYOUT)]
        runner, code, out = launched(
            {run: ok({"address": "t9"})},
            "--space", "Project", "--tab", "Worker", "--name", "w1", "--cwd", "/tmp/repo",
            layouts=layouts,
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["address"], "t9")
        self.assertEqual(out["placed"]["space"], {"id": "sp1", "name": "Project"})
        self.assertEqual(out["placed"]["tab"]["id"], "tb2")

    def test_types_into_an_interactive_bash_never_a_bare_hc_run(self):
        run = run_args(["herdr.space=sp1", "herdr.tab=tb2"])
        runner, _, _ = launched(
            {run: ok({"address": "t9"})},
            "--space", "sp1", "--tab", "tb2", "--name", "w1",
            layouts=[ok(LAYOUT), ok(LAYOUT)],
        )
        spawn = runner.ran("hc", "run")[0]
        self.assertIn("-ic", spawn)
        self.assertEqual(spawn[spawn.index("--") + 1], SHELL)
        self.assertEqual(spawn[spawn.index("-ic") + 1], '"$@"; exec "$0" -i')

    def test_worker_of_uses_the_worker_tab_of_that_terminals_space(self):
        run = run_args(["herdr.space=sp1", "herdr.tab=tb2"])
        conductor = ok({"address": "t1", "labels": {"herdr.space": "sp1"}})
        runner, code, out = launched(
            {run: ok({"address": "t9"}), ("hc", "get", "t1", "--json"): conductor},
            "--worker-of", "t1", "--name", "w1",
            layouts=[ok(LAYOUT), ok(LAYOUT)],
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["placed"]["tab"]["id"], "tb2")

    def test_names_a_new_tab_once_the_app_has_adopted_the_terminal(self):
        run = run_args(["herdr.space=sp1"])
        rename = ("herdr-app", "do", "tab.rename", "--id", "tb9", "--name", "Review")
        runner, code, out = launched(
            {run: ok({"address": "t9"}), rename: ok({})},
            "--space", "sp1", "--tab", "Review", "--name", "w1",
            layouts=[ok(LAYOUT), ok(WITH_NEW)],
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["placed"]["tab"], {"id": "tb9", "name": "Review"})
        self.assertEqual(len(runner.ran("herdr-app", "do", "tab.rename")), 1)

    def test_waits_with_hc_wait_for_the_app_to_adopt_the_terminal(self):
        run = run_args(["herdr.space=sp1"])
        rename = ("herdr-app", "do", "tab.rename", "--id", "tb9", "--name", "Review")
        runner, _, _ = launched(
            {run: ok({"address": "t9"}), rename: ok({})},
            "--space", "sp1", "--tab", "Review", "--name", "w1",
            layouts=[ok(LAYOUT), ok(LAYOUT), ok(WITH_NEW)],
        )
        self.assertGreaterEqual(
            len(runner.ran("hc", "wait", "t9", "--timeout", "2")), 1
        )

    def test_without_a_flag_the_caller_becomes_the_parent(self):
        run = run_args(["herdr.space=sp1", "herdr.tab=tb2"], parent="t1")
        clock = FakeClock()
        runner = FakeRunner(
            {
                PS: SESSION_PROCESSES,
                ("hc", "get", "t1", "--json"): ok(
                    {"address": "t1", "pid": 800, "labels": {}}
                ),
                ("herdr-app", "ls"): [ok(LAYOUT), ok(LAYOUT), ok(LAYOUT)],
                run: ok({"address": "t9"}),
                ("hc", "wait", "t9", "--timeout", "2", "--json"): ok({"ended": False}),
                ("hc", "get", "t9", "--json"): [
                    record(agent_status("working")),
                    record(agent_status("idle")),
                ],
                ("hc", "read", "t9", "--lines", "0", "--json"): [
                    screen(PROMPT),
                    screen(READY),
                ],
                **{
                    (
                        "hc", "wait", "t9", "--timeout", str(n), "--json",
                        "--output", "bypass permissions on",
                    ): ok({"ended": False})
                    for n in range(1, 6)
                },
            },
            clock=clock,
        )
        runner.responses[PS] = [SESSION_PROCESSES, SHELL_RUNNING, SHELL_RUNNING]
        code, out = run_verb(
            ["launch", "--space", "sp1", "--tab", "tb2", "--name", "w1"],
            runner,
            {"HC_TERMINAL_ID": "t1"},
            clock=clock,
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(runner.ran("hc", "run")), 1)

    def test_no_parent_leaves_the_terminal_unparented(self):
        run = run_args(["herdr.space=sp1", "herdr.tab=tb2"])
        runner, code, _ = launched(
            {run: ok({"address": "t9"})},
            "--space", "sp1", "--tab", "tb2", "--name", "w1", "--no-parent",
            layouts=[ok(LAYOUT), ok(LAYOUT)],
        )
        self.assertEqual(code, 0)

    def test_an_unknown_space_exits_three_without_starting_anything(self):
        runner, code, out = launched({}, "--space", "Nowhere", "--name", "w1")
        self.assertEqual(code, 3)
        self.assertEqual(runner.ran("hc", "run"), [])

    def test_a_closed_window_exits_one_without_starting_anything(self):
        runner, code, out = launched(
            {}, "--space", "sp1", "--name", "w1", layouts=[failed(1, text="no window")]
        )
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "no_window")
        self.assertEqual(runner.ran("hc", "run"), [])

    def test_a_name_hc_would_refuse_is_a_usage_error(self):
        runner, code, out = launched({}, "--space", "sp1", "--name", "Bad Name")
        self.assertEqual(code, 2)
        self.assertEqual(runner.ran("hc", "run"), [])

    def test_a_failed_hc_run_exits_one(self):
        run = run_args(["herdr.space=sp1", "herdr.tab=tb2"])
        reply = failed(1, {"error": {"kind": "name_taken", "message": "name in use"}})
        _, code, out = launched(
            {run: reply}, "--space", "sp1", "--tab", "tb2", "--name", "w1"
        )
        self.assertEqual(code, 1)
        self.assertEqual(out["reason"], "name in use")

    def test_placing_a_new_terminal_is_app_only(self):
        code, out = run_verb(
            ["--backend", "tui", "launch", "--space", "w1"], FakeRunner({})
        )
        self.assertEqual(code, 2)
        self.assertIn("app-only", out["reason"])


if __name__ == "__main__":
    unittest.main()
