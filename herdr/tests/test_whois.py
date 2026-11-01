import json
import tempfile
import unittest
from pathlib import Path

from support import (
    PS,
    SESSION,
    FakeRunner,
    failed,
    not_found,
    ok,
    processes,
    run_verb,
)

LABELS = {
    "claude.session": SESSION,
    "claude.name": "reviewer",
    "claude.model": "sonnet",
    "claude.effort": "high",
    "claude.cwd": "/tmp/repo",
    "where": "Project / Worker",
}


def record(labels=None, status=None, pid=800, parent="t1"):
    return {
        "address": "t7",
        "name": "review",
        "pid": pid,
        "cwd": "/tmp/other",
        "parent": parent,
        "state": "live",
        "labels": LABELS if labels is None else labels,
        "status": status or {"app": "claude-code", "state": "idle"},
    }


def tree(agent_args):
    return processes(
        (800, 1, "pts/3", "-bash"),
        (810, 800, "pts/3", "op run -- claude"),
        (820, 810, "pts/3", agent_args),
    )


def app_runner(rec, table):
    return FakeRunner(
        {PS: table, ("hc", "get", "t7", "--json"): ok(rec)},
    )


class WhoisFromLabels(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        projects = Path(self.home.name, ".claude", "projects", "-tmp-repo")
        projects.mkdir(parents=True)
        self.transcript = projects / f"{SESSION}.jsonl"
        self.transcript.write_text("{}\n")

    def whois(self, *extra, rec=None, table=None):
        runner = app_runner(rec or record(), table or tree("claude --model sonnet"))
        return run_verb(
            ["--backend", "app", "whois", "t7", *extra], runner, home=self.home.name
        )

    def test_reports_the_identity_the_labels_record(self):
        code, out = self.whois()
        self.assertEqual(code, 0)
        self.assertEqual(out["kind"], "claude")
        self.assertEqual(out["session"], SESSION)
        self.assertEqual(out["session_source"], "label")
        self.assertEqual(out["name"], "reviewer")
        self.assertEqual(out["model"], "sonnet")
        self.assertEqual(out["effort"], "high")
        self.assertEqual(out["cwd"], "/tmp/repo")
        self.assertEqual(out["parent"], "t1")
        self.assertEqual(out["where"], "Project / Worker")
        self.assertEqual(out["labels"], LABELS)
        self.assertEqual(out["degraded"], [])

    def test_finds_the_transcript_by_session_id(self):
        _, out = self.whois()
        self.assertEqual(out["transcript"], str(self.transcript))

    def test_builds_the_exact_resume_command_with_bypass_by_default(self):
        _, out = self.whois()
        self.assertEqual(
            out["resume"],
            {
                "cwd": "/tmp/repo",
                "command": f"claude --resume {SESSION} --permission-mode "
                "bypassPermissions --model sonnet --effort high",
            },
        )

    def test_permission_flag_replaces_the_default(self):
        _, out = self.whois("--permission-flag", "--permission-mode plan")
        self.assertIn("--permission-mode plan", out["resume"]["command"])
        self.assertNotIn("bypassPermissions", out["resume"]["command"])

    def test_reports_the_open_dialog_of_a_blocked_terminal(self):
        status = {
            "app": "claude-code",
            "state": "blocked",
            "kind": "question",
            "msg": "Trust this folder? (Yes, No)",
        }
        _, out = self.whois(rec=record(status=status))
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(
            out["dialog"], {"kind": "question", "msg": "Trust this folder? (Yes, No)"}
        )

    def test_unknown_terminal_exits_three(self):
        runner = FakeRunner({PS: tree("claude"), ("hc", "get", "t9", "--json"): not_found()})
        code, out = run_verb(["--backend", "app", "whois", "t9"], runner)
        self.assertEqual(code, 3)
        self.assertEqual(out["error"], "not_found")


class WhoisWithoutLabels(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)

    def whois(self, agent_args, rec=None):
        runner = app_runner(rec or record(labels={}), tree(agent_args))
        return run_verb(["--backend", "app", "whois", "t7"], runner, home=self.home.name)

    def write_session_file(self, pid=820, **fields):
        sessions = Path(self.home.name, ".claude", "sessions")
        sessions.mkdir(parents=True)
        (sessions / f"{pid}.json").write_text(json.dumps(fields))

    def test_reads_the_session_file_of_the_agent_process(self):
        self.write_session_file(sessionId=SESSION, name="derived", cwd="/tmp/repo")
        _, out = self.whois("/opt/claude/claude --model opus --effort xhigh")
        self.assertEqual(out["session"], SESSION)
        self.assertEqual(out["session_source"], "sessions-file")
        self.assertEqual(out["name"], "review")
        self.assertEqual(out["model"], "opus")
        self.assertEqual(out["effort"], "xhigh")
        self.assertEqual(out["agent_pid"], 820)
        self.assertEqual(len(out["degraded"]), 1)

    def test_falls_back_to_the_resume_flag_when_there_is_no_session_file(self):
        _, out = self.whois(f"claude --resume {SESSION} --model opus")
        self.assertEqual(out["session"], SESSION)
        self.assertEqual(out["session_source"], "argv")
        self.assertIn(f"claude --resume {SESSION}", out["resume"]["command"])

    def test_reports_an_unknown_session_without_failing(self):
        code, out = self.whois("claude --model opus")
        self.assertEqual(code, 0)
        self.assertIsNone(out["session"])
        self.assertIsNone(out["session_source"])
        self.assertIsNone(out["resume"])
        self.assertIsNone(out["transcript"])
        self.assertIn("none found", out["degraded"][0])

    def test_finds_an_agent_that_the_terminal_does_not_report_on(self):
        rec = record(labels={}, status={})
        rec["status"] = None
        _, out = self.whois(f"claude --resume {SESSION}", rec=rec)
        self.assertEqual(out["kind"], "claude")

    def test_codex_resume_command_keeps_the_app_flags(self):
        rec = record(labels={}, status={"app": "codex", "state": "idle"})
        args = (
            f"codex resume {SESSION} --model gpt-x "
            "-c model_reasoning_effort=\"xhigh\""
        )
        table = processes(
            (800, 1, "pts/3", "-bash"), (820, 800, "pts/3", args)
        )
        runner = app_runner(rec, table)
        _, out = run_verb(["--backend", "app", "whois", "t7"], runner, home=self.home.name)
        self.assertEqual(out["kind"], "codex")
        self.assertEqual(out["session"], SESSION)
        self.assertEqual(out["effort"], "xhigh")
        self.assertEqual(
            out["resume"]["command"],
            f"codex resume {SESSION} --dangerously-bypass-approvals-and-sandbox "
            "--no-daemon --model gpt-x -c 'model_reasoning_effort=\"xhigh\"'",
        )


class WhoisOutsideHerdr(unittest.TestCase):
    def test_a_tmux_seat_has_no_backend_to_ask(self):
        runner = FakeRunner(
            {
                PS: processes((800, 1, "pts/3", "-bash"), (902, 800, "?", "python3")),
                ("tmux", "display-message", "-p", "-t", "%4", "#{pane_tty}"): ok(
                    "/dev/pts/3\n"
                ),
            }
        )
        code, out = run_verb(["whois", "t7"], runner, {"TMUX_PANE": "%4"})
        self.assertEqual(code, 4)
        self.assertIn("tmux", out["reason"])

    def test_no_seat_means_no_backend_to_ask(self):
        runner = FakeRunner({PS: processes((902, 1, "?", "python3"))})
        code, out = run_verb(["whois", "t7"], runner, {})
        self.assertEqual(code, 4)
        self.assertEqual(out["error"], "no_seat")


class WhoisInTheTui(unittest.TestCase):
    def test_reads_the_session_from_the_herdr_agent_record(self):
        agent = {
            "pane_id": "w1:p2",
            "workspace_id": "w1",
            "tab_id": "w1:t1",
            "name": "reviewer",
            "agent": "claude",
            "agent_status": "idle",
            "cwd": "/tmp/repo",
            "agent_session": {"agent": "claude", "value": SESSION},
        }
        runner = FakeRunner(
            {
                PS: tree("claude --model opus"),
                ("herdr", "agent", "get", "reviewer"): ok({"result": {"agent": agent}}),
                ("herdr", "pane", "process-info", "--pane", "w1:p2"): ok(
                    {"result": {"process_info": {"pane_id": "w1:p2", "shell_pid": 800}}}
                ),
                ("herdr", "workspace", "get", "w1"): ok(
                    {"result": {"workspace": {"label": "Project"}}}
                ),
                ("herdr", "tab", "get", "w1:t1"): ok({"result": {"tab": {"label": "Worker"}}}),
            }
        )
        code, out = run_verb(["--backend", "tui", "whois", "reviewer"], runner)
        self.assertEqual(code, 0)
        self.assertEqual(out["target"], "w1:p2")
        self.assertEqual(out["session"], SESSION)
        self.assertEqual(out["session_source"], "herdr")
        self.assertEqual(out["model"], "opus")
        self.assertEqual(out["where"], "Project / Worker")
        self.assertEqual(out["degraded"], [])

    def test_unknown_agent_exits_three(self):
        missing = failed(1, {"error": {"code": "agent_not_found", "message": "no agent"}})
        runner = FakeRunner(
            {
                ("herdr", "agent", "get", "ghost"): missing,
                ("herdr", "pane", "get", "ghost"): missing,
            }
        )
        code, out = run_verb(["--backend", "tui", "whois", "ghost"], runner)
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
