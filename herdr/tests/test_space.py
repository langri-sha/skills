import unittest

from support import FakeRunner, failed, ok, run_verb

EXISTING = {
    "spaces": [
        {
            "id": "sp1",
            "name": "Alpha",
            "active": True,
            "tabs": [{"id": "tb1", "name": "Main"}],
        },
        {"id": "sp2", "name": "Beta", "active": False, "tabs": []},
    ]
}
CREATED = {
    "spaces": [
        *EXISTING["spaces"],
        {
            "id": "sp3",
            "name": "Gamma",
            "active": True,
            "tabs": [{"id": "tb3", "name": "Conductor"}],
        },
    ]
}
NEW = (
    "herdr-app",
    "do",
    "space.new",
    "--name",
    "Gamma",
    "--folder",
    "/tmp/repo",
    "--tab",
    "Conductor",
)


def app(responses):
    runner = FakeRunner({("herdr-app", "ls"): [ok(EXISTING), ok(CREATED)], **responses})
    return runner, lambda *argv: run_verb(["--backend", "app", "space", *argv], runner)


class SpaceInTheApp(unittest.TestCase):
    def test_creates_the_space_and_reports_its_first_tab(self):
        runner, run = app({NEW: ok({"space": "sp3"})})
        code, out = run("Gamma", "--folder", "/tmp/repo", "--tab", "Conductor")
        self.assertEqual(code, 0)
        self.assertEqual(out["space"], {"id": "sp3", "name": "Gamma"})
        self.assertEqual(out["tab"], {"id": "tb3", "name": "Conductor"})
        self.assertIs(out["focus_restored"], False)
        self.assertEqual(runner.ran("herdr-app", "do", "space.select"), [])

    def test_refuses_a_name_that_is_taken_whatever_its_case(self):
        runner, run = app({})
        code, out = run("alpha", "--folder", "/tmp/repo")
        self.assertEqual(code, 5)
        self.assertEqual(out["error"], "space_exists")
        self.assertEqual(out["existing"], [{"id": "sp1", "name": "Alpha"}])
        self.assertEqual(runner.ran("herdr-app", "do"), [])

    def test_keep_focus_brings_the_previous_space_back(self):
        select = ("herdr-app", "do", "space.select", "--id", "sp1")
        runner, run = app({NEW: ok({"space": "sp3"}), select: ok({})})
        code, out = run(
            "Gamma", "--folder", "/tmp/repo", "--tab", "Conductor", "--keep-focus"
        )
        self.assertEqual(code, 0)
        self.assertIs(out["focus_restored"], True)
        self.assertEqual(len(runner.ran("herdr-app", "do", "space.select")), 1)

    def test_reports_the_error_the_window_gives(self):
        _, run = app({NEW: ok({"error": "folder does not exist"})})
        code, out = run("Gamma", "--folder", "/tmp/repo", "--tab", "Conductor")
        self.assertEqual(code, 1)
        self.assertEqual(out["reason"], "folder does not exist")

    def test_a_closed_window_is_reported(self):
        runner = FakeRunner({("herdr-app", "ls"): failed(1, text="no window")})
        code, out = run_verb(
            ["--backend", "app", "space", "Gamma", "--folder", "/tmp/repo"], runner
        )
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "no_window")


def tui(responses):
    runner = FakeRunner(
        {
            ("herdr", "workspace", "list"): ok(
                {"result": {"workspaces": [{"workspace_id": "w1", "label": "Alpha"}]}}
            ),
            **responses,
        }
    )
    return runner, lambda *argv: run_verb(["--backend", "tui", "space", *argv], runner)


CREATE = {
    "result": {
        "workspace": {"workspace_id": "w2", "label": "Gamma"},
        "tab": {"tab_id": "w2:t1", "label": "1"},
    }
}


class SpaceInTheTui(unittest.TestCase):
    def test_creates_an_unfocused_workspace_and_names_its_first_tab(self):
        create = (
            "herdr",
            "workspace",
            "create",
            "--label",
            "Gamma",
            "--cwd",
            "/tmp/repo",
            "--no-focus",
        )
        rename = ("herdr", "tab", "rename", "w2:t1", "Conductor")
        _, run = tui({create: ok(CREATE), rename: ok({})})
        code, out = run(
            "Gamma", "--folder", "/tmp/repo", "--tab", "Conductor", "--keep-focus"
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["space"], {"id": "w2", "name": "Gamma"})
        self.assertEqual(out["tab"], {"id": "w2:t1", "name": "Conductor"})

    def test_focuses_the_new_workspace_without_keep_focus(self):
        create = (
            "herdr",
            "workspace",
            "create",
            "--label",
            "Gamma",
            "--cwd",
            "/tmp/repo",
            "--focus",
        )
        _, run = tui({create: ok(CREATE)})
        code, out = run("Gamma", "--folder", "/tmp/repo")
        self.assertEqual(code, 0)
        self.assertIs(out["focus_restored"], False)

    def test_refuses_a_label_that_is_taken(self):
        _, run = tui({})
        code, out = run("ALPHA", "--folder", "/tmp/repo")
        self.assertEqual(code, 5)
        self.assertEqual(out["existing"], [{"id": "w1", "name": "Alpha"}])


if __name__ == "__main__":
    unittest.main()
