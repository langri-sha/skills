import unittest

from support import FakeRunner, failed, not_found, ok, run_verb

BODY = "line one\n\n  \nline two\nline three\n\nline four\nline five\n"
FOOTER = "─────\n❯\n─────\n   Opus 5.5 · high\n  ⏵⏵ bypass permissions on\n"


def hc_read(text, complete=True, why=None):
    reply = {"complete": complete, "how": "screen", "text": text}
    if why:
        reply["why"] = why
    return ok(reply)


def app(responses):
    runner = FakeRunner(responses)
    return runner, lambda *argv: run_verb(["--backend", "app", *argv], runner)


class ReadInTheApp(unittest.TestCase):
    def test_returns_the_screen_and_history_as_text(self):
        runner, run = app({("hc", "read", "t7", "--lines", "400", "--json"): hc_read(BODY)})
        code, out = run("read", "t7")
        self.assertEqual(code, 0)
        self.assertEqual(out["text"], BODY.rstrip("\n"))
        self.assertIs(out["complete"], True)
        self.assertIs(out["screen_only"], False)

    def test_tail_drops_blank_lines_and_keeps_the_last_n(self):
        _, run = app({("hc", "read", "t7", "--lines", "400", "--json"): hc_read(BODY)})
        _, out = run("read", "t7", "--tail", "3")
        self.assertEqual(out["text"], "line three\nline four\nline five")

    def test_footer_returns_the_last_five_non_blank_lines_of_the_screen_only(self):
        runner, run = app({("hc", "read", "t7", "--lines", "0", "--json"): hc_read(BODY + FOOTER)})
        _, out = run("read", "t7", "--footer")
        self.assertEqual(
            out["text"].splitlines(),
            ["line five", "─────", "❯", "─────", "   Opus 5.5 · high", "  ⏵⏵ bypass permissions on"][-5:],
        )
        self.assertEqual(runner.ran("hc", "wait"), [])

    def test_waits_once_when_only_the_screen_is_available_then_reads_again(self):
        first = hc_read("screen", complete=False, why="working")
        second = hc_read("screen and history")
        runner, run = app(
            {
                ("hc", "read", "t7", "--lines", "400", "--json"): [first, second],
                ("hc", "wait", "t7", "--timeout", "30", "--json"): ok({"status": "idle"}),
            }
        )
        _, out = run("read", "t7")
        self.assertEqual(out["text"], "screen and history")
        self.assertIs(out["waited"], True)
        self.assertIs(out["screen_only"], False)
        self.assertEqual(len(runner.ran("hc", "wait")), 1)

    def test_reports_screen_only_when_the_terminal_is_still_working(self):
        working = hc_read("screen", complete=False, why="working")
        runner, run = app(
            {
                ("hc", "read", "t7", "--lines", "400", "--json"): working,
                ("hc", "wait", "t7", "--timeout", "5", "--json"): ok({"status": "working"}),
            }
        )
        _, out = run("read", "t7", "--wait-timeout", "5")
        self.assertIs(out["screen_only"], True)
        self.assertIs(out["waited"], True)
        self.assertEqual(len(runner.ran("hc", "read")), 2)
        self.assertEqual(len(runner.ran("hc", "wait")), 1)

    def test_unknown_terminal_exits_three(self):
        _, run = app({("hc", "read", "t9", "--lines", "400", "--json"): not_found()})
        code, out = run("read", "t9")
        self.assertEqual(code, 3)
        self.assertEqual(out["error"], "not_found")

    def test_other_hc_failures_exit_one_with_their_message(self):
        reply = failed(1, {"error": {"kind": "io", "message": "core unreachable"}})
        _, run = app({("hc", "read", "t7", "--lines", "400", "--json"): reply})
        code, out = run("read", "t7")
        self.assertEqual(code, 1)
        self.assertEqual(out["reason"], "core unreachable")


def tui_reply(text, truncated=False):
    return ok({"result": {"read": {"text": text, "truncated": truncated}}})


NOT_IDLE = failed(1, {"error": {"code": "agent_not_idle", "message": "agent is working"}})


class ReadInTheTui(unittest.TestCase):
    def run_tui(self, responses, *argv):
        runner = FakeRunner(responses)
        return runner, run_verb(["--backend", "tui", *argv], runner)

    def test_reads_recent_unwrapped_history(self):
        runner, (code, out) = self.run_tui(
            {
                ("herdr", "agent", "read", "w1:p2", "--source", "recent-unwrapped", "--lines", "400"): tui_reply(BODY)
            },
            "read",
            "w1:p2",
        )
        self.assertEqual(code, 0)
        self.assertIsNone(out["fallback"])
        self.assertEqual(out["text"], BODY.rstrip("\n"))

    def test_falls_back_to_visible_and_says_so_when_the_agent_is_not_idle(self):
        _, (code, out) = self.run_tui(
            {
                ("herdr", "agent", "read", "rev", "--source", "recent-unwrapped", "--lines", "400"): NOT_IDLE,
                ("herdr", "agent", "read", "rev", "--source", "visible", "--lines", "400"): tui_reply("screen"),
            },
            "read",
            "rev",
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["fallback"], "visible")
        self.assertIs(out["screen_only"], True)
        self.assertEqual(out["text"], "screen")

    def test_gives_up_when_even_the_visible_read_is_not_idle(self):
        gone = failed(1, {"error": {"code": "pane_not_found", "message": "no pane"}})
        _, (code, out) = self.run_tui(
            {
                ("herdr", "agent", "read", "rev", "--source", "recent-unwrapped", "--lines", "400"): NOT_IDLE,
                ("herdr", "agent", "read", "rev", "--source", "visible", "--lines", "400"): NOT_IDLE,
                ("herdr", "pane", "read", "rev", "--source", "visible", "--lines", "400"): gone,
            },
            "read",
            "rev",
        )
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "agent_not_idle")

    def test_reads_a_plain_pane_that_hosts_no_agent(self):
        not_agent = failed(1, {"error": {"code": "agent_not_found", "message": "no agent"}})
        _, (code, out) = self.run_tui(
            {
                ("herdr", "agent", "read", "w1:p3", "--source", "recent-unwrapped", "--lines", "400"): not_agent,
                ("herdr", "pane", "read", "w1:p3", "--source", "recent-unwrapped", "--lines", "400"): tui_reply("$ ls"),
            },
            "read",
            "w1:p3",
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["text"], "$ ls")

    def test_footer_reads_only_the_visible_screen(self):
        _, (_, out) = self.run_tui(
            {("herdr", "agent", "read", "rev", "--source", "visible"): tui_reply(BODY + FOOTER)},
            "read",
            "rev",
            "--footer",
        )
        self.assertEqual(len(out["text"].splitlines()), 5)


if __name__ == "__main__":
    unittest.main()
