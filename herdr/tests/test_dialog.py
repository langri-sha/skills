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
        self.assertEqual(out["answerable"], "folder-trust")

    def test_options_come_from_the_message_when_the_screen_lists_none(self):
        _, _, out = dialog({GET: blocked("Sign in? (Yes · Not now)"), READ: screen("")})
        self.assertEqual(out["dialog"]["options"], ["Yes", "Not now"])

    def test_reports_no_dialog_when_the_terminal_is_not_blocked(self):
        _, code, out = dialog({GET: idle(), READ: screen("")})
        self.assertEqual(code, 0)
        self.assertIsNone(out["dialog"])

    def test_other_dialogs_are_not_answerable(self):
        _, _, out = dialog({GET: blocked("Allow edit?", "permission"), READ: screen(EDIT)})
        self.assertIsNone(out["answerable"])


class AnswerTheDialog(unittest.TestCase):
    def test_answers_the_folder_trust_dialog_with_the_listed_option(self):
        keys = ("hc", "keys", "t7", "enter", "--json")
        runner, code, out = dialog(
            {GET: [blocked("Trust this folder?"), idle()], READ: screen(TRUST), keys: ok({})},
            "--answer",
            "1",
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["answered"], "Yes, I trust this folder")
        self.assertEqual(out["status"], "idle")
        self.assertEqual(runner.ran("hc", "keys"), [keys])

    def test_moves_down_to_a_later_option_before_pressing_enter(self):
        keys = ("hc", "keys", "t7", "down", "enter", "--json")
        runner, code, out = dialog(
            {GET: [blocked("Trust this folder?"), idle()], READ: screen(TRUST), keys: ok({})},
            "--answer",
            "no, exit",
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["answered"], "No, exit")

    def test_refuses_a_permission_dialog_and_presses_nothing(self):
        runner, code, out = dialog(
            {GET: blocked("Allow edit?", "permission"), READ: screen(EDIT)},
            "--answer",
            "1",
        )
        self.assertEqual(code, 9)
        self.assertEqual(out["error"], "not_allowed")
        self.assertEqual(out["dialog"]["options"][0], "Yes")
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_refuses_a_dialog_that_only_mentions_the_folder_in_a_tool_prompt(self):
        text = "Do you want to proceed?\n Bash command in this folder\n ❯ 1. Yes\n   2. No\n"
        runner, code, _ = dialog(
            {GET: blocked("Run it?", "permission"), READ: screen(text)}, "--answer", "1"
        )
        self.assertEqual(code, 9)
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_refuses_a_permission_dialog_whatever_the_screen_says(self):
        runner, code, out = dialog(
            {GET: blocked("Trust this folder?", "permission"), READ: screen(TRUST)},
            "--answer",
            "1",
        )
        self.assertEqual(code, 9)
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_trust_words_in_the_scrollback_do_not_make_a_permission_dialog_trusted(self):
        text = (
            "I will trust this folder and run the build.\n"
            + "output line\n" * 12
            + "Would you like to run the following command?\n"
            " ❯ 1. Yes, proceed\n   2. No\n"
        )
        runner, code, _ = dialog(
            {GET: blocked("Run it?", "permission"), READ: screen(text)}, "--answer", "1"
        )
        self.assertEqual(code, 9)
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_trust_words_in_the_scrollback_do_not_make_a_question_trusted(self):
        text = (
            "Do you trust the files in this folder? yes, I trust this folder\n"
            + "output line\n" * 12
            + "Which branch should I push?\n ❯ 1. main\n   2. feature\n"
        )
        runner, code, out = dialog(
            {GET: blocked("Which branch?"), READ: screen(text)}, "--answer", "1"
        )
        self.assertEqual(code, 9)
        self.assertEqual(out["error"], "not_allowed")
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_the_trust_dialog_is_still_answered_with_old_output_above_it(self):
        text = (
            "1. earlier list item\n2. another one\n"
            + "output line\n" * 12
            + TRUST
        )
        keys = ("hc", "keys", "t7", "down", "enter", "--json")
        runner, code, out = dialog(
            {GET: [blocked("Trust?"), idle()], READ: screen(text), keys: ok({})},
            "--answer",
            "2",
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["answered"], "No, exit")

    def test_refuses_any_other_question(self):
        runner, code, _ = dialog(
            {GET: blocked("Sign in?"), READ: screen(SIGN_IN)}, "--answer", "1"
        )
        self.assertEqual(code, 9)
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_an_answer_that_matches_no_option_is_a_usage_error(self):
        runner, code, out = dialog(
            {GET: blocked("Trust this folder?"), READ: screen(TRUST)}, "--answer", "maybe"
        )
        self.assertEqual(code, 2)
        self.assertEqual(out["options"], ["Yes, I trust this folder", "No, exit"])
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_an_answer_with_no_dialog_open_exits_eight(self):
        _, code, out = dialog({GET: idle(), READ: screen("")}, "--answer", "1")
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "no_dialog")


class DialogInTheTui(unittest.TestCase):
    def test_answers_a_folder_trust_dialog_through_agent_keys(self):
        agent = lambda state: ok({"result": {"agent": {"agent_status": state}}})
        runner = FakeRunner(
            {
                ("herdr", "agent", "get", "rev"): [agent("blocked"), agent("idle")],
                ("herdr", "agent", "read", "rev", "--source", "visible"): ok(
                    {"result": {"read": {"text": TRUST}}}
                ),
                ("herdr", "agent", "send-keys", "rev", "enter"): ok({}),
            }
        )
        code, out = run_verb(["--backend", "tui", "dialog", "rev", "--answer", "yes"], runner)
        self.assertEqual(code, 0)
        self.assertEqual(out["status"], "idle")


if __name__ == "__main__":
    unittest.main()
