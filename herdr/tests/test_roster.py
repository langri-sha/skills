import unittest

from support import FakeRunner, failed, ok, run_verb

BYPASS = "──\n❯\n──\n  Opus 5.5 · high\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
AUTO = "──\n❯\n──\n  ⏵⏵ auto mode on (shift+tab to cycle)\n"
CODEX = "› Ask\n  gpt-x xhigh · ~/repo\n"
SHELL_ONLY = "$ \n"


def listed(address, agent, status=None, state="live", **extra):
    row = {"address": address, "agent": agent, "cwd": "/tmp/repo", "state": state, "turn": 1}
    if status:
        row["status"] = status
    return {**row, **extra}


def record(address, app=None, state="idle", labels=None, **status):
    reported = {"app": app, "state": state, **status} if app else None
    return {"address": address, "labels": labels or {}, "status": reported}


def screen(text):
    return ok({"complete": True, "how": "screen", "text": text})


def app_runner(extra=None, terminals=None):
    base = {
        ("hc", "ls", "--json"): ok(
            {
                "terminals": terminals
                or [
                    listed("t1", "claude-code", "idle", name="lead", where="Project / Conductor"),
                    listed("t2", "claude-code", "working", name="worker", parent="t1", where="Project / Worker"),
                    listed("t3", "claude-code", "blocked", where="Project / Worker"),
                    listed("t4", "codex", "idle", where="Project / Worker"),
                    listed("t5", "bash", where="Project / Worker"),
                ]
            }
        ),
        ("hc", "get", "t1", "--json"): ok(record("t1", "claude-code", labels={"claude.session": "s-1", "claude.cwd": "/tmp/lead"})),
        ("hc", "get", "t2", "--json"): ok(record("t2", "claude-code", "working")),
        (
            "hc",
            "get",
            "t3",
            "--json",
        ): ok(record("t3", "claude-code", "blocked", kind="question", msg="Trust this folder? (Yes, No)")),
        ("hc", "get", "t4", "--json"): ok(record("t4", "codex")),
        ("hc", "get", "t5", "--json"): ok(record("t5")),
        ("hc", "read", "t1", "--lines", "0", "--json"): screen(BYPASS),
        ("hc", "read", "t2", "--lines", "0", "--json"): screen(AUTO),
        ("hc", "read", "t4", "--lines", "0", "--json"): screen(CODEX),
    }
    return FakeRunner({**base, **(extra or {})})


def rows_by_address(argv, runner):
    code, out = run_verb(["--backend", "app", *argv], runner)
    return code, out, {row["address"]: row for row in out.get("terminals", [])}


class RosterInTheApp(unittest.TestCase):
    def test_lists_one_row_per_terminal(self):
        code, out, rows = rows_by_address(["roster"], app_runner())
        self.assertEqual(code, 0)
        self.assertEqual(out["count"], 5)
        self.assertEqual(list(rows), ["t1", "t2", "t3", "t4", "t5"])

    def test_row_carries_identity_state_and_place(self):
        _, _, rows = rows_by_address(["roster"], app_runner())
        lead = rows["t1"]
        self.assertEqual(lead["name"], "lead")
        self.assertEqual(lead["kind"], "claude")
        self.assertEqual(lead["state"], "live")
        self.assertEqual(lead["status"], "idle")
        self.assertEqual(lead["where"], "Project / Conductor")
        self.assertEqual(lead["session"], "s-1")
        self.assertEqual(lead["cwd"], "/tmp/lead")
        self.assertEqual(rows["t2"]["parent"], "t1")

    def test_prefers_the_session_name_label_over_the_terminal_name(self):
        runner = app_runner(
            {
                ("hc", "get", "t1", "--json"): ok(
                    record("t1", "claude-code", labels={"claude.name": "reviewer"})
                )
            }
        )
        _, _, rows = rows_by_address(["roster"], runner)
        self.assertEqual(rows["t1"]["name"], "reviewer")

    def test_reads_the_permission_mode_from_the_claude_footer(self):
        _, _, rows = rows_by_address(["roster"], app_runner())
        self.assertIs(rows["t1"]["bypass"], True)
        self.assertEqual(rows["t1"]["permission_mode"], "bypass")
        self.assertIs(rows["t2"]["bypass"], False)
        self.assertEqual(rows["t2"]["permission_mode"], "auto")

    def test_leaves_bypass_unknown_for_codex_and_plain_shells(self):
        _, _, rows = rows_by_address(["roster"], app_runner())
        self.assertIsNone(rows["t4"]["bypass"])
        self.assertEqual(rows["t4"]["kind"], "codex")
        self.assertIsNone(rows["t5"]["bypass"])
        self.assertEqual(rows["t5"]["kind"], "bash")

    def test_reports_the_open_dialog_and_leaves_bypass_unknown(self):
        runner = app_runner()
        _, _, rows = rows_by_address(["roster"], runner)
        self.assertEqual(
            rows["t3"]["dialog"],
            {"kind": "question", "msg": "Trust this folder? (Yes, No)"},
        )
        self.assertEqual(rows["t3"]["status"], "blocked")
        self.assertIsNone(rows["t3"]["bypass"])
        self.assertEqual(runner.ran("hc", "read", "t3"), [])

    def test_passes_label_filters_to_hc(self):
        runner = FakeRunner(
            {
                ("hc", "ls", "--json", "--label", "team=a", "--label", "role=lead"): ok(
                    {"terminals": [listed("t1", "claude-code", "idle")]}
                ),
                ("hc", "get", "t1", "--json"): ok(record("t1", "claude-code")),
                ("hc", "read", "t1", "--lines", "0", "--json"): screen(BYPASS),
            }
        )
        code, out, _ = rows_by_address(
            ["roster", "--label", "team=a", "--label", "role=lead"], runner
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["count"], 1)

    def test_an_unreadable_footer_leaves_bypass_unknown_without_failing(self):
        runner = app_runner({("hc", "read", "t1", "--lines", "0", "--json"): failed(1, text="gone")})
        code, _, rows = rows_by_address(["roster"], runner)
        self.assertEqual(code, 0)
        self.assertIsNone(rows["t1"]["bypass"])

    def test_hc_failure_exits_one(self):
        runner = FakeRunner({("hc", "ls", "--json"): failed(1, {"error": {"kind": "io", "message": "core down"}})})
        code, out, _ = rows_by_address(["roster"], runner)
        self.assertEqual(code, 1)
        self.assertEqual(out["reason"], "core down")


def pane(pane_id, agent=None, status="unknown", **extra):
    return {
        "pane_id": pane_id,
        "workspace_id": "w1",
        "tab_id": "w1:t1",
        "agent": agent,
        "agent_status": status,
        "cwd": "/tmp/repo",
        **extra,
    }


def tui_reply(key, items):
    return ok({"result": {key: items}})


def tui_screen(text):
    return ok({"result": {"read": {"text": text}}})


class RosterInTheTui(unittest.TestCase):
    def runner(self):
        return FakeRunner(
            {
                ("herdr", "agent", "list"): tui_reply(
                    "agents", [{"pane_id": "w1:p1", "name": "reviewer"}]
                ),
                ("herdr", "workspace", "list"): tui_reply(
                    "workspaces", [{"workspace_id": "w1", "label": "Project"}]
                ),
                ("herdr", "tab", "list"): tui_reply("tabs", [{"tab_id": "w1:t1", "label": "Worker"}]),
                ("herdr", "pane", "list"): tui_reply(
                    "panes",
                    [
                        pane("w1:p1", "claude", "idle", agent_session={"agent": "claude", "value": "s-9"}),
                        pane("w1:p2", "claude", "blocked"),
                        pane("w1:p3"),
                    ],
                ),
                ("herdr", "pane", "read", "w1:p1", "--source", "visible"): tui_screen(BYPASS),
                ("herdr", "pane", "read", "w1:p2", "--source", "visible"): tui_screen("Trust this folder?\n1. Yes\n2. No\n"),
            }
        )

    def rows(self):
        code, out = run_verb(["--backend", "tui", "roster"], self.runner())
        self.assertEqual(code, 0)
        return {row["address"]: row for row in out["terminals"]}

    def test_row_carries_name_place_session_and_mode(self):
        row = self.rows()["w1:p1"]
        self.assertEqual(row["name"], "reviewer")
        self.assertEqual(row["where"], "Project / Worker")
        self.assertEqual(row["session"], "s-9")
        self.assertEqual(row["status"], "idle")
        self.assertIs(row["bypass"], True)

    def test_blocked_pane_carries_the_screen_as_its_dialog(self):
        row = self.rows()["w1:p2"]
        self.assertIsNone(row["dialog"]["kind"])
        self.assertIn("Trust this folder?", row["dialog"]["msg"])
        self.assertIsNone(row["bypass"])

    def test_plain_pane_has_no_agent_fields(self):
        row = self.rows()["w1:p3"]
        self.assertIsNone(row["kind"])
        self.assertIsNone(row["bypass"])

    def test_label_filters_are_a_usage_error(self):
        code, out = run_verb(["--backend", "tui", "roster", "--label", "a=b"], self.runner())
        self.assertEqual(code, 2)
        self.assertEqual(out["error"], "usage")


if __name__ == "__main__":
    unittest.main()
