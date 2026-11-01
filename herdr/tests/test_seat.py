import unittest

from support import (
    OTHER_SESSION,
    PS,
    SESSION,
    SESSION_PROCESSES,
    FakeRunner,
    ok,
    failed,
    processes,
    run_verb,
)

LAYOUT = {
    "spaces": [
        {
            "id": "sp1",
            "name": "Project",
            "tabs": [
                {"id": "tb1", "name": "Conductor", "terminals": [{"terminal": "t1"}]},
                {"id": "tb2", "name": "Worker", "terminals": [{"terminal": "t7"}]},
            ],
        }
    ]
}


def terminal(pid=800, labels=None):
    return {"address": "t7", "pid": pid, "labels": labels or {}}


def app_runner(record, layout=LAYOUT, table=SESSION_PROCESSES):
    return FakeRunner(
        {
            PS: table,
            ("hc", "get", "t7", "--json"): ok(record),
            ("herdr-app", "ls"): ok(layout) if layout else failed(1, text="no window"),
        }
    )


class SeatInTheApp(unittest.TestCase):
    environ = {"HC_TERMINAL_ID": "t7", "CLAUDE_CODE_SESSION_ID": SESSION}

    def test_reports_the_terminal_space_and_tab_from_the_window(self):
        runner = app_runner(terminal(labels={"claude.session": SESSION}))
        code, out = run_verb(["seat"], runner, self.environ)
        self.assertEqual(code, 0)
        self.assertEqual(out["backend"], "app")
        self.assertEqual(out["target"], "t7")
        self.assertEqual(out["terminal"], "t7")
        self.assertEqual(out["space"], {"id": "sp1", "name": "Project"})
        self.assertEqual(out["tab"], {"id": "tb2", "name": "Worker"})
        self.assertEqual(out["tty"], "pts/3")

    def test_matching_session_label_means_this_is_not_a_background_job(self):
        runner = app_runner(terminal(labels={"claude.session": SESSION}))
        _, out = run_verb(["seat"], runner, self.environ)
        self.assertIs(out["session_match"], True)
        self.assertIs(out["background_job"], False)

    def test_other_session_label_marks_a_background_job(self):
        runner = app_runner(terminal(labels={"claude.session": OTHER_SESSION}))
        _, out = run_verb(["seat"], runner, self.environ)
        self.assertIs(out["session_match"], False)
        self.assertIs(out["background_job"], True)

    def test_missing_session_label_degrades_to_unknown_with_a_reason(self):
        runner = app_runner(terminal())
        code, out = run_verb(["seat"], runner, self.environ)
        self.assertEqual(code, 0)
        self.assertIsNone(out["session_match"])
        self.assertIsNone(out["background_job"])
        self.assertIn("claude.session", out["session_reason"])

    def test_unset_session_environment_degrades_to_unknown_with_a_reason(self):
        runner = app_runner(terminal(labels={"claude.session": SESSION}))
        _, out = run_verb(["seat"], runner, {"HC_TERMINAL_ID": "t7"})
        self.assertIsNone(out["session_match"])
        self.assertIn("CLAUDE_CODE_SESSION_ID", out["session_reason"])

    def test_falls_back_to_labels_when_the_window_is_closed(self):
        labels = {
            "herdr.space": "sp1",
            "herdr.tab": "tb2",
            "where": "Project / Worker",
        }
        runner = app_runner(terminal(labels=labels), layout=None)
        _, out = run_verb(["seat"], runner, self.environ)
        self.assertEqual(out["space"], {"id": "sp1", "name": "Project"})
        self.assertEqual(out["tab"], {"id": "tb2", "name": "Worker"})

    def test_inherited_terminal_of_another_tty_is_rejected(self):
        runner = app_runner(terminal(pid=4242))
        runner.responses[PS] = processes(
            (800, 1, "pts/3", "-bash"),
            (4242, 1, "pts/8", "-bash"),
            (902, 800, "?", "python3 herdr.py"),
        )
        code, out = run_verb(["seat"], runner, self.environ)
        self.assertEqual(code, 4)
        self.assertEqual(out["error"], "no_seat")
        self.assertFalse(out["ok"])


class SeatInTmux(unittest.TestCase):
    def test_tmux_pane_on_the_same_tty_wins_over_the_inherited_terminal(self):
        runner = app_runner(terminal(labels={"claude.session": SESSION}))
        runner.responses[
            ("tmux", "display-message", "-p", "-t", "%4", "#{pane_tty}")
        ] = ok("/dev/pts/3\n")
        environ = {"HC_TERMINAL_ID": "t7", "TMUX_PANE": "%4"}
        code, out = run_verb(["seat"], runner, environ)
        self.assertEqual(code, 0)
        self.assertEqual(out["backend"], "tmux")
        self.assertEqual(out["pane"], "%4")

    def test_tmux_pane_on_another_tty_is_ignored(self):
        runner = FakeRunner(
            {
                PS: SESSION_PROCESSES,
                ("tmux", "display-message", "-p", "-t", "%4", "#{pane_tty}"): ok(
                    "/dev/pts/12\n"
                ),
            }
        )
        code, out = run_verb(["seat"], runner, {"TMUX_PANE": "%4"})
        self.assertEqual(code, 4)
        self.assertEqual(out["error"], "no_seat")


class SeatInTheTui(unittest.TestCase):
    environ = {
        "HERDR_ENV": "1",
        "HERDR_PANE_ID": "w1:p2",
        "CLAUDE_CODE_SESSION_ID": SESSION,
    }

    def runner(self, tty="/dev/pts/3", session=SESSION):
        pane = {
            "pane_id": "w1:p2",
            "workspace_id": "w1",
            "tab_id": "w1:t1",
            "agent_session": {"agent": "claude", "value": session},
        }
        return FakeRunner(
            {
                PS: SESSION_PROCESSES,
                ("herdr", "pane", "process-info", "--pane", "w1:p2"): ok(
                    {
                        "result": {
                            "process_info": {
                                "pane_id": "w1:p2",
                                "shell_pid": 800,
                                "tty": tty,
                            }
                        }
                    }
                ),
                ("herdr", "pane", "get", "w1:p2"): ok({"result": {"pane": pane}}),
                ("herdr", "workspace", "get", "w1"): ok(
                    {"result": {"workspace": {"label": "Project"}}}
                ),
                ("herdr", "tab", "get", "w1:t1"): ok(
                    {"result": {"tab": {"label": "Worker"}}}
                ),
            }
        )

    def test_reports_the_pane_workspace_and_tab(self):
        code, out = run_verb(["seat"], self.runner(), self.environ)
        self.assertEqual(code, 0)
        self.assertEqual(out["backend"], "tui")
        self.assertEqual(out["target"], "w1:p2")
        self.assertEqual(out["workspace"], {"id": "w1", "name": "Project"})
        self.assertEqual(out["tab"], {"id": "w1:t1", "name": "Worker"})
        self.assertIs(out["session_match"], True)

    def test_targets_the_pane_explicitly_and_never_the_current_one(self):
        runner = self.runner()
        run_verb(["seat"], runner, self.environ)
        for call in runner.calls:
            self.assertNotIn("--current", call)

    def test_pane_on_another_tty_is_rejected(self):
        code, out = run_verb(["seat"], self.runner(tty="/dev/pts/40"), self.environ)
        self.assertEqual(code, 4)

    def test_other_session_in_the_pane_marks_a_background_job(self):
        _, out = run_verb(
            ["seat"], self.runner(session=OTHER_SESSION), self.environ
        )
        self.assertIs(out["background_job"], True)

    def test_tui_variables_without_the_herdr_marker_are_ignored(self):
        environ = {"HERDR_PANE_ID": "w1:p2"}
        runner = FakeRunner({PS: SESSION_PROCESSES})
        code, _ = run_verb(["seat"], runner, environ)
        self.assertEqual(code, 4)


class SeatWithoutATerminal(unittest.TestCase):
    def test_a_tree_without_any_tty_has_no_seat(self):
        table = processes((902, 1, "?", "python3 herdr.py"))
        code, out = run_verb(["seat"], FakeRunner({PS: table}), {})
        self.assertEqual(code, 4)
        self.assertEqual(out["error"], "no_seat")
        self.assertIn("controlling terminal", out["reason"])

    def test_bad_usage_exits_two_with_a_json_line(self):
        code, out = run_verb(["frobnicate"], FakeRunner({}), {})
        self.assertEqual(code, 2)
        self.assertEqual(out["error"], "usage")


if __name__ == "__main__":
    unittest.main()
