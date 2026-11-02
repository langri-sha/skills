import unittest

from support import FakeClock, FakeRunner, failed, ok, run_verb

GET = ("hc", "get", "t7", "--json")
LS = ("herdr-app", "ls")
PARK = ("herdr-app", "do", "terminal.park", "--terminal", "t7")
PACE = ("hc", "wait", "t7", "--timeout", "2", "--json", "--output", "herdr-pace-sentinel")


def layout(placed_in=None):
    spaces = [
        {
            "id": "sp1",
            "name": "Old",
            "tabs": [{"id": "tb1", "name": "Worker", "terminals": []}],
        },
        {
            "id": "sp2",
            "name": "New",
            "tabs": [{"id": "tb2", "name": "Worker", "terminals": []}],
        },
    ]
    if placed_in:
        for space in spaces:
            for tab in space["tabs"]:
                if tab["id"] == placed_in:
                    tab["terminals"].append({"terminal": "t7"})
    return ok({"spaces": spaces})


def record(keep=True, where="Old / Worker", state="live"):
    return ok(
        {
            "address": "t7",
            "state": state,
            "keep": keep,
            "labels": {"herdr.space": "sp1", "herdr.tab": "tb1", "where": where},
        }
    )


def move(responses, *argv):
    clock = FakeClock()
    runner = FakeRunner({PACE: ok({"ended": False}), **responses}, clock=clock)
    code, out = run_verb(["--backend", "app", "move", "t7", *argv], runner, clock=clock)
    return runner, code, out


def label(space, tab):
    return ("hc", "label", "t7", f"herdr.space={space}", f"herdr.tab={tab}", "--json")


class MoveInTheApp(unittest.TestCase):
    def test_parks_waits_for_the_pane_to_drop_relabels_and_verifies(self):
        runner, code, out = move(
            {
                GET: [record(), record(where="New / Worker")],
                LS: [layout("tb1"), layout(), layout("tb2")],
                PARK: ok({"pending": True}),
                label("sp2", "tb2"): ok({}),
            },
            "--space",
            "New",
            "--tab",
            "Worker",
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["where"], "New / Worker")
        self.assertIs(out["keep"], True)
        order = [call[:3] for call in runner.calls if call[0] in ("herdr-app", "hc") and call[1] in ("do", "label")]
        self.assertEqual(
            order,
            [("herdr-app", "do", "terminal.park"), ("hc", "label", "t7")],
        )

    def test_names_a_new_space_and_tab_once_adopted(self):
        new_layout = layout("tb1")
        adopted = ok(
            {
                "spaces": [
                    {"id": "mission", "name": "x", "tabs": [{"id": "lead", "name": "1", "terminals": [{"terminal": "t7"}]}]}
                ]
            }
        )
        dropped = ok({"spaces": []})
        runner, code, out = move(
            {
                GET: [record(), record(where="Plan / Conductor")],
                LS: [new_layout, dropped, adopted],
                PARK: ok({"pending": True}),
                label("mission", "lead"): ok({}),
                ("herdr-app", "do", "space.rename", "--id", "mission", "--name", "Plan"): ok({}),
                ("herdr-app", "do", "tab.rename", "--id", "lead", "--name", "Conductor"): ok({}),
            },
            "--space",
            "mission",
            "--tab",
            "lead",
            "--space-name",
            "Plan",
            "--tab-name",
            "Conductor",
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(runner.ran("herdr-app", "do", "space.rename")), 1)
        self.assertEqual(len(runner.ran("herdr-app", "do", "tab.rename")), 1)

    def test_puts_the_terminal_back_when_the_app_keeps_the_pane(self):
        runner, code, out = move(
            {
                GET: record(),
                LS: layout("tb1"),
                PARK: ok({"pending": True}),
                ("hc", "keep", "t7", "--json"): ok({}),
                label("sp1", "tb1"): ok({}),
            },
            "--space",
            "New",
            "--tab",
            "Worker",
        )
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "pane_kept")
        self.assertIs(out["rolled_back"], True)
        self.assertEqual(len(runner.ran("hc", "keep")), 1)
        self.assertEqual(runner.ran("hc", "label"), [label("sp1", "tb1")])
        self.assertTrue(all(call[0] != "sleep" for call in runner.calls))

    def test_puts_the_terminal_back_when_the_new_place_never_adopts_it(self):
        runner, code, out = move(
            {
                GET: record(),
                LS: [layout("tb1"), layout()],
                PARK: ok({"pending": True}),
                label("sp2", "tb2"): ok({}),
                ("hc", "keep", "t7", "--json"): ok({}),
                label("sp1", "tb1"): ok({}),
            },
            "--space",
            "New",
            "--tab",
            "Worker",
        )
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "not_adopted")
        self.assertEqual(
            runner.ran("hc", "label"), [label("sp2", "tb2"), label("sp1", "tb1")]
        )

    def test_a_terminal_that_lost_keep_is_kept_again_and_verified(self):
        runner, code, out = move(
            {
                GET: [record(), record(keep=False, where="New / Worker"), record(where="New / Worker")],
                LS: [layout("tb1"), layout(), layout("tb2")],
                PARK: ok({"pending": True}),
                label("sp2", "tb2"): ok({}),
                ("hc", "keep", "t7", "--json"): ok({}),
            },
            "--space",
            "New",
            "--tab",
            "Worker",
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(runner.ran("hc", "keep")), 1)
        self.assertIs(out["keep"], True)

    def test_a_terminal_that_stays_unkept_is_reported(self):
        _, code, out = move(
            {
                GET: [record(), record(keep=False, where="New / Worker")],
                LS: [layout("tb1"), layout(), layout("tb2")],
                PARK: ok({"pending": True}),
                label("sp2", "tb2"): ok({}),
                ("hc", "keep", "t7", "--json"): ok({}),
            },
            "--space",
            "New",
            "--tab",
            "Worker",
        )
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "unverified")

    def test_a_failed_park_changes_nothing(self):
        runner, code, out = move(
            {
                GET: record(),
                LS: layout("tb1"),
                PARK: failed(1, {"error": "no such terminal"}),
            },
            "--space",
            "New",
            "--tab",
            "Worker",
        )
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "park_failed")
        self.assertEqual(runner.ran("hc", "label"), [])

    def test_a_finished_terminal_exits_eleven(self):
        _, code, _ = move(
            {GET: record(state="finished")}, "--space", "New", "--tab", "Worker"
        )
        self.assertEqual(code, 11)


def tui(responses, *argv):
    base = {
        ("herdr", "workspace", "list"): ok(
            {"result": {"workspaces": [{"workspace_id": "w2", "label": "New"}]}}
        ),
        ("herdr", "tab", "list", "--workspace", "w2"): ok(
            {"result": {"tabs": [{"tab_id": "w2:t1", "label": "Worker"}]}}
        ),
    }
    runner = FakeRunner({**base, **responses})
    return runner, run_verb(["--backend", "tui", "move", "w1:p1", *argv], runner)


def moved(pane="w2:p5"):
    return ok(
        {"result": {"move_result": {"pane": {"pane_id": pane}, "previous_pane_id": "w1:p1"}}}
    )


class MoveInTheTui(unittest.TestCase):
    def test_splits_into_an_existing_tab_and_reports_the_new_pane_id(self):
        command = ("herdr", "pane", "move", "w1:p1", "--tab", "w2:t1", "--split", "down", "--no-focus")
        _, (code, out) = tui({command: moved()}, "--space", "New", "--tab", "Worker")
        self.assertEqual(code, 0)
        self.assertEqual(out["target"], "w2:p5")
        self.assertEqual(out["previous"], "w1:p1")

    def test_opens_a_new_tab_in_an_existing_workspace(self):
        command = ("herdr", "pane", "move", "w1:p1", "--new-tab", "--workspace", "w2", "--label", "Review", "--no-focus")
        _, (code, _) = tui({command: moved()}, "--space", "New", "--tab", "Review")
        self.assertEqual(code, 0)

    def test_opens_a_new_workspace_with_a_named_tab(self):
        command = (
            "herdr", "pane", "move", "w1:p1", "--new-workspace", "--label", "Plan",
            "--tab-label", "Conductor", "--no-focus",
        )
        _, (code, _) = tui({command: moved("w3:p1")}, "--space", "Plan", "--tab", "Conductor")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
