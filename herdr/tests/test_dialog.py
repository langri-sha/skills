import unittest

from support import FakeRunner, ok, run_verb

GET = ("hc", "get", "t7", "--json")
READ = ("hc", "read", "t7", "--lines", "0", "--json")

TRUST = (
    "Do you trust the files in this folder?\n"
    " ❯ 1. Yes, I trust this folder\n"
    "   2. No, exit\n"
)
EDIT = (
    "Do you want to make this edit to notes.md?\n"
    " ❯ 1. Yes\n"
    "   2. Yes, allow all edits during this session\n"
    "   3. No\n"
)
SIGN_IN = "Delta needs you to sign in.\n ❯ 1. Sign in\n   2. Not now\n"


def blocked(msg, kind="question"):
    return ok(
        {
            "address": "t7",
            "state": "live",
            "status": {"app": "claude-code", "state": "blocked", "kind": kind, "msg": msg},
        }
    )


def idle():
    return ok({"address": "t7", "state": "live", "status": {"app": "claude-code", "state": "idle"}})


def screen(text):
    return ok({"complete": True, "how": "screen", "text": text})


def dialog(responses, *argv):
    runner = FakeRunner(responses)
    code, out = run_verb(["--backend", "app", "dialog", "t7", *argv], runner)
    return runner, code, out


class ShowTheDialog(unittest.TestCase):
    def test_returns_kind_message_options_and_whether_it_is_answerable(self):
        _, code, out = dialog({GET: blocked("Trust this folder?"), READ: screen(TRUST)})
        self.assertEqual(code, 0)
        self.assertEqual(out["dialog"]["kind"], "question")
        self.assertEqual(out["dialog"]["msg"], "Trust this folder?")
        self.assertEqual(out["dialog"]["options"], ["Yes, I trust this folder", "No, exit"])

    def test_options_come_from_the_message_when_the_screen_lists_none(self):
        _, _, out = dialog({GET: blocked("Sign in? (Yes · Not now)"), READ: screen("")})
        self.assertEqual(out["dialog"]["options"], ["Yes", "Not now"])

    def test_reports_no_dialog_when_the_terminal_is_not_blocked(self):
        _, code, out = dialog({GET: idle(), READ: screen("")})
        self.assertEqual(code, 0)
        self.assertIsNone(out["dialog"])


class DialogInTheTui(unittest.TestCase):
    def test_returns_the_visible_screen_of_a_blocked_agent(self):
        agent = ok({"result": {"agent": {"agent_status": "blocked"}}})
        runner = FakeRunner(
            {
                ("herdr", "agent", "get", "rev"): agent,
                ("herdr", "agent", "read", "rev", "--source", "visible"): ok(
                    {"result": {"read": {"text": TRUST}}}
                ),
            }
        )
        code, out = run_verb(["--backend", "tui", "dialog", "rev"], runner)
        self.assertEqual(code, 0)
        self.assertEqual(out["dialog"]["options"], ["Yes, I trust this folder", "No, exit"])


if __name__ == "__main__":
    unittest.main()
