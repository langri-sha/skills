import shlex
import unittest

from support import PS, SESSION_PROCESSES, FakeRunner, ok, run_verb


def watch(*argv, environ=None, backend="app"):
    runner = FakeRunner({})
    return run_verb(["--backend", backend, "watch", *argv], runner, environ)


class WatchLabels(unittest.TestCase):
    def test_prints_an_events_command_filtered_to_the_label(self):
        code, out = watch("--label", "team=alpha")
        self.assertEqual(code, 0)
        words = shlex.split(out["command"].split(" | ")[0])
        self.assertEqual(words, ["hc", "events", "--json", "--label", "team=alpha"])

    def test_every_label_must_match(self):
        _, out = watch("--label", "team=alpha", "--label", "role=lead")
        self.assertIn("--label team=alpha --label role=lead", out["command"])

    def test_pipes_status_finished_and_lost_events_through_jq(self):
        _, out = watch("--label", "team=alpha")
        self.assertIn("jq --unbuffered -c", out["command"])
        for kind in ("status", "finished", "lost"):
            self.assertIn(f'.params.type == "{kind}"', out["command"])

    def test_quotes_a_label_with_spaces(self):
        _, out = watch("--label", "team=big team")
        self.assertIn("'team=big team'", out["command"])

    def test_a_label_without_a_value_is_a_usage_error(self):
        code, out = watch("--label", "team")
        self.assertEqual(code, 2)

    def test_children_of_follows_a_terminal_s_children(self):
        _, out = watch("--children-of", "t1")
        self.assertIn("--children-of t1", out["command"])

    def test_defaults_to_the_callers_children(self):
        runner = FakeRunner(
            {
                PS: SESSION_PROCESSES,
                ("hc", "get", "t1", "--json"): ok({"address": "t1", "pid": 800, "labels": {}}),
                ("herdr-app", "ls"): ok({"spaces": []}),
            }
        )
        code, out = run_verb(["watch"], runner, {"HC_TERMINAL_ID": "t1"})
        self.assertEqual(code, 0)
        self.assertIn("--children-of t1", out["command"])

    def test_without_a_filter_or_a_seat_it_asks_for_one(self):
        code, out = watch()
        self.assertEqual(code, 2)

    def test_the_tui_has_no_event_stream(self):
        code, out = watch("--label", "a=b", backend="tui")
        self.assertEqual(code, 2)
        self.assertIn("app-only", out["reason"])


if __name__ == "__main__":
    unittest.main()
