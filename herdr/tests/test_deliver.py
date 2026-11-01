import tempfile
import unittest
from pathlib import Path

from support import FakeRunner, failed, ok, run_verb

GET = ("hc", "get", "t7", "--json")
READ = ("hc", "read", "t7", "--lines", "0", "--json")


def record(state="idle", turn=3, **status):
    return ok(
        {
            "address": "t7",
            "state": "live",
            "turn": turn,
            "status": {"app": "claude-code", "state": state, **status},
        }
    )


def sent(started=True, turn=3, status="idle"):
    return ok({"started": started, "status": status, "turn": turn})


def deliver(responses, *argv):
    runner = FakeRunner({READ: ok({"text": "history\nprompt\n"}), **responses})
    code, out = run_verb(["--backend", "app", "deliver", "t7", *argv], runner)
    return runner, code, out


class DeliverInTheApp(unittest.TestCase):
    def test_sends_and_confirms_the_agent_is_working(self):
        runner, code, out = deliver(
            {
                GET: [record("idle"), record("working", turn=4)],
                ("hc", "send", "t7", "do the thing", "--json"): sent(),
            },
            "do the thing",
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["confirmed"], "working")
        self.assertEqual(len(runner.ran("hc", "send")), 1)

    def test_accepts_a_turn_that_already_finished(self):
        _, code, out = deliver(
            {
                GET: [record("idle"), record("idle", turn=4)],
                ("hc", "send", "t7", "quick", "--json"): sent(),
            },
            "quick",
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["confirmed"], "turn")

    def test_refuses_a_blocked_terminal_and_returns_its_dialog(self):
        blocked = record("blocked", kind="permission", msg="Allow edit? (Yes, No)")
        runner, code, out = deliver({GET: blocked}, "hello")
        self.assertEqual(code, 9)
        self.assertEqual(out["error"], "blocked")
        self.assertEqual(out["dialog"]["kind"], "permission")
        self.assertEqual(out["dialog"]["options"], ["Yes", "No"])
        self.assertEqual(runner.ran("hc", "send"), [])

    def test_a_dialog_that_opens_between_the_check_and_the_send_is_returned(self):
        blocked = record("blocked", kind="question", msg="Sign in? (Yes, No)")
        refused = failed(9, {"error": {"kind": "blocked", "message": "blocked"}})
        runner, code, out = deliver(
            {GET: [record("idle"), blocked], ("hc", "send", "t7", "hi", "--json"): refused},
            "hi",
        )
        self.assertEqual(code, 9)
        self.assertEqual(out["dialog"]["msg"], "Sign in? (Yes, No)")

    def test_a_send_that_did_not_start_is_read_back_and_never_resent(self):
        runner, code, out = deliver(
            {
                GET: record("idle"),
                ("hc", "send", "t7", "hi", "--json"): sent(started=False),
            },
            "hi",
        )
        self.assertEqual(code, 10)
        self.assertEqual(out["error"], "unconfirmed")
        self.assertEqual(out["screen"], ["history", "prompt"])
        self.assertEqual(len(runner.ran("hc", "send")), 1)

    def test_a_program_that_reports_no_status_is_unconfirmed(self):
        _, code, out = deliver(
            {GET: record("idle"), ("hc", "send", "t7", "hi", "--json"): sent(started=None)},
            "hi",
        )
        self.assertEqual(code, 10)

    def test_waits_once_for_working_and_then_gives_up(self):
        wait = ("hc", "wait", "t7", "--timeout", "15", "--json")
        runner, code, _ = deliver(
            {
                GET: record("idle"),
                wait: ok({"ended": True}),
                ("hc", "send", "t7", "hi", "--json"): sent(),
            },
            "hi",
        )
        self.assertEqual(code, 10)
        self.assertEqual(len(runner.ran("hc", "wait")), 1)
        self.assertEqual(len(runner.ran("hc", "send")), 1)

    def test_reads_the_text_from_a_file(self):
        with tempfile.TemporaryDirectory() as folder:
            brief = Path(folder, "brief.md")
            brief.write_text("# Brief\nDo it\n")
            runner, code, _ = deliver(
                {
                    GET: [record("idle"), record("working", turn=4)],
                    ("hc", "send", "t7", "# Brief\nDo it\n", "--json"): sent(),
                },
                "--file",
                str(brief),
            )
        self.assertEqual(code, 0)

    def test_the_text_and_a_file_together_are_a_usage_error(self):
        _, code, _ = deliver({}, "hi", "--file", "x")
        self.assertEqual(code, 2)

    def test_nothing_to_send_is_a_usage_error(self):
        _, code, _ = deliver({}, "  ")
        self.assertEqual(code, 2)

    def test_a_missing_file_is_a_usage_error(self):
        _, code, out = deliver({}, "--file", "/nonexistent/brief.md")
        self.assertEqual(code, 2)
        self.assertIn("cannot read", out["reason"])

    def test_a_finished_terminal_exits_eleven(self):
        gone = ok({"address": "t7", "state": "finished", "status": None})
        _, code, _ = deliver({GET: gone}, "hi")
        self.assertEqual(code, 11)


PROMPT = ("herdr", "agent", "prompt", "rev", "hello")
VISIBLE = ("herdr", "agent", "read", "rev", "--source", "visible")


def tui(responses, text="hello"):
    runner = FakeRunner(
        {VISIBLE: ok({"result": {"read": {"text": "1. Yes\n2. No\n"}}}), **responses}
    )
    return runner, run_verb(["--backend", "tui", "deliver", "rev", text], runner)


class DeliverInTheTui(unittest.TestCase):
    def test_prompts_the_agent(self):
        reply = ok({"result": {"agent": {"agent_status": "working"}}})
        runner, (code, out) = tui({PROMPT: reply})
        self.assertEqual(code, 0)
        self.assertEqual(out["confirmed"], "herdr")
        self.assertEqual(out["status"], "working")

    def test_returns_the_screen_of_a_blocked_agent(self):
        blocked = failed(1, {"error": {"code": "agent_blocked", "message": "blocked"}})
        _, (code, out) = tui({PROMPT: blocked})
        self.assertEqual(code, 9)
        self.assertEqual(out["dialog"]["options"], ["Yes", "No"])

    def test_a_stalled_prompt_is_unconfirmed(self):
        stalled = failed(1, {"error": {"code": "agent_prompt_stalled", "message": "x"}})
        _, (code, out) = tui({PROMPT: stalled})
        self.assertEqual(code, 10)
        self.assertEqual(out["screen"], ["1. Yes", "2. No"])


if __name__ == "__main__":
    unittest.main()
