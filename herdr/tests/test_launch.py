import unittest
import tempfile
from pathlib import Path
import shlex

from support import (
    agent_status,
    screen,
    PS,
    FakeClock,
    FakeRunner,
    failed,
    ok,
    processes,
    run_verb,
)

SHELL_ONLY = processes((800, 1, "pts/3", "/usr/bin/bash -i"))
SHELL_RUNNING = processes(
    (800, 1, "pts/3", "/usr/bin/bash -i"),
    (810, 800, "pts/3", "/opt/agents/claude --model sonnet"),
)
SHELL_BUSY = processes(
    (800, 1, "pts/3", "/usr/bin/bash -i"), (810, 800, "pts/3", "vim notes.md")
)
LOGIN_SHELL = processes((800, 1, "pts/3", "-bash"))
BANNER = " ▐▛███▜▌   Claude Code\n  Sonnet 5.5 · Claude Max\n"
READY = BANNER + "──\n❯\n──\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
PROMPT = "$ \n"

COMMAND = "claude --permission-mode bypassPermissions --model sonnet --effort high"
SEND = ("hc", "send", "t7", COMMAND, "--json")
READ = ("hc", "read", "t7", "--lines", "0", "--json")
GET = ("hc", "get", "t7", "--json")


def terminal(status=None, state="live", reported=False, pid=800):
    record = {
        "address": "t7",
        "pid": pid,
        "state": state,
        "reported": reported,
        "labels": {},
        "status": status,
    }
    return ok(record)


TIMED_OUT = ok({"ended": False, "reason": "timeout", "terminal": "t7"})
SENT = ok({"started": None, "status": None, "turn": 0})


def launch(responses, *argv, clock=None):
    clock = clock or FakeClock()
    runner = FakeRunner(responses, clock=clock)
    code, out = run_verb(
        ["--backend", "app", "launch", "--in", "t7", *argv], runner, clock=clock
    )
    return runner, code, out


def scenario(overrides=None):
    base = {
        GET: [
            terminal(),
            terminal(agent_status("working")),
            terminal(agent_status("idle")),
        ],
        PS: [SHELL_ONLY, SHELL_RUNNING],
        READ: [screen(PROMPT), screen(PROMPT + "claude ...\n"), screen(READY)],
        SEND: SENT,
        **{
            ("hc", "wait", "t7", "--timeout", str(seconds), "--json", "--output", "herdr-pace-sentinel"): TIMED_OUT
            for seconds in range(1, 6)
        },
    }
    return {**base, **(overrides or {})}


class LaunchIntoAShell(unittest.TestCase):
    ARGS = ("--model", "sonnet", "--effort", "high")

    def test_reports_ready_when_idle_with_the_bypass_footer_and_the_model_banner(self):
        runner, code, out = launch(scenario(), *self.ARGS)
        self.assertEqual(code, 0)
        self.assertEqual(out["address"], "t7")
        self.assertEqual(out["status"], "idle")
        self.assertEqual(out["permission_mode"], "bypass")
        self.assertIs(out["model_shown"], True)
        self.assertEqual(out["command"], COMMAND)

    def test_types_the_command_into_the_shell_exactly_once(self):
        runner, _, _ = launch(scenario(), *self.ARGS)
        self.assertEqual(len(runner.ran("hc", "send")), 1)
        self.assertEqual(runner.ran("hc", "run"), [])

    def test_waits_with_hc_wait_and_never_sleeps(self):
        runner, _, _ = launch(scenario(), *self.ARGS)
        self.assertGreaterEqual(len(runner.ran("hc", "wait")), 1)
        self.assertEqual(runner.ran("sleep"), [])

    def test_changes_directory_first_when_cwd_is_given(self):
        send = ("hc", "send", "t7", f"cd '/tmp/my repo' && {COMMAND}", "--json")
        responses = {**scenario(), send: SENT}
        del responses[SEND]
        runner, code, _ = launch(responses, *self.ARGS, "--cwd", "/tmp/my repo")
        self.assertEqual(code, 0)
        self.assertEqual(runner.ran("hc", "send")[0][3], send[3])

    def test_a_login_shell_counts_as_an_idle_shell(self):
        _, code, _ = launch(scenario({PS: [LOGIN_SHELL, SHELL_RUNNING]}), *self.ARGS)
        self.assertEqual(code, 0)

    def test_returns_the_dialog_with_its_kind_message_and_options(self):
        dialog = agent_status("blocked", kind="question", msg="Trust this folder?")
        text = "Do you trust this folder?\n ❯ 1. Yes, I trust this folder\n   2. No, exit\n"
        runner, code, out = launch(
            scenario({GET: [terminal(), terminal(dialog)], READ: [screen(PROMPT), screen(text)]}),
            *self.ARGS,
        )
        self.assertEqual(code, 9)
        self.assertEqual(out["error"], "blocked")
        self.assertEqual(
            out["dialog"],
            {
                "kind": "question",
                "msg": "Trust this folder?",
                "options": ["Yes, I trust this folder", "No, exit"],
            },
        )

    def test_reports_a_launcher_failure_without_retrying(self):
        text = PROMPT + "error: authorization prompt dismissed\n" + PROMPT
        runner, code, out = launch(
            scenario({READ: [screen(PROMPT), screen(text)]}), *self.ARGS
        )
        self.assertEqual(code, 6)
        self.assertEqual(out["error"], "launcher_failed")
        self.assertIn("authorization prompt dismissed", out["reason"])
        self.assertEqual(len(runner.ran("hc", "send")), 1)

    def test_every_default_failure_pattern_is_caught(self):
        for line in (
            "authorization timeout",
            "connecting to desktop app timed out",
        ):
            with self.subTest(line=line):
                _, code, out = launch(
                    scenario({READ: [screen(PROMPT), screen(PROMPT + line + "\n")]}),
                    *self.ARGS,
                )
                self.assertEqual(code, 6)

    def test_extra_failure_patterns_are_matched_too(self):
        _, code, out = launch(
            scenario({READ: [screen(PROMPT), screen(PROMPT + "vault is locked\n")]}),
            *self.ARGS,
            "--fail-pattern",
            "vault is locked",
        )
        self.assertEqual(code, 6)
        self.assertIn("vault is locked", out["reason"])

    def test_a_failure_line_that_was_already_on_screen_does_not_count(self):
        stale = PROMPT + "error: authorization timeout\n"
        _, code, _ = launch(
            scenario({READ: [screen(stale), screen(stale), screen(stale + READY)]}),
            *self.ARGS,
        )
        self.assertEqual(code, 0)

    def test_reports_the_shell_prompt_coming_back(self):
        runner, code, out = launch(
            scenario(
                {
                    GET: [terminal(), terminal(agent_status("idle"))],
                    PS: [SHELL_ONLY],
                    READ: [screen(PROMPT)],
                }
            ),
            *self.ARGS,
        )
        self.assertEqual(code, 6)
        self.assertEqual(out["error"], "shell_returned")

    def test_an_idle_agent_is_ready_when_a_narrow_terminal_cuts_the_footer(self):
        clock = FakeClock()
        _, code, out = launch(
            scenario(
                {
                    GET: [terminal(), terminal(agent_status("idle"))],
                    READ: [screen(PROMPT), screen("❯\n───────\n  Opus 5.5\n  ⏵⏵ bypass\n")],
                }
            ),
            "--timeout",
            "180",
            *self.ARGS,
            clock=clock,
        )
        self.assertEqual(code, 0)
        self.assertIsNone(out["permission_mode"])
        self.assertLess(clock.seconds, 10)

    def test_times_out_with_the_last_state_it_saw(self):
        _, code, out = launch(
            scenario(
                {
                    GET: [terminal(), terminal(agent_status("working"))],
                    READ: [screen(PROMPT), screen(BANNER)],
                }
            ),
            "--timeout",
            "12",
            *self.ARGS,
        )
        self.assertEqual(code, 7)
        self.assertEqual(out["status"], "working")
        self.assertGreaterEqual(out["elapsed_s"], 12)

    def test_the_ended_terminal_exits_eleven(self):
        _, code, out = launch(
            scenario({GET: [terminal(), terminal(state="finished")]}), *self.ARGS
        )
        self.assertEqual(code, 11)

    def test_reports_the_model_banner_without_waiting_on_it(self):
        _, code, out = launch(
            scenario({READ: [screen(PROMPT), screen(PROMPT), screen(READY.replace("Sonnet", "Haiku"))]}),
            *self.ARGS,
        )
        self.assertEqual(code, 0)
        self.assertIs(out["model_shown"], False)

    def test_options_come_from_the_last_run_of_numbered_lines_only(self):
        text = (
            "1. old list item\n2. another old item\n"
            + "output line\n" * 12
            + "Which branch should I push?\n ❯ 1. main\n   2. feature\n"
        )
        dialog = agent_status("blocked", kind="question", msg="Which branch?")
        _, code, out = launch(
            scenario({GET: [terminal(), terminal(dialog)], READ: [screen(PROMPT), screen(text)]}),
            *self.ARGS,
        )
        self.assertEqual(code, 9)
        self.assertEqual(out["dialog"]["options"], ["main", "feature"])

    def test_a_custom_permission_flag_expects_its_own_footer(self):
        command = "claude --permission-mode plan"
        runner = FakeRunner(
            scenario(
                {
                    SEND: None,
                    ("hc", "send", "t7", command, "--json"): SENT,
                    READ: [screen(PROMPT), screen(PROMPT), screen("──\n  ⏵⏵ plan mode on\n")],
                                        ("hc", "wait", "t7", "--timeout", "5", "--json", "--output", "herdr-pace-sentinel"): TIMED_OUT,
                }
            ),
            clock=FakeClock(),
        )
        code, out = run_verb(
            [
                "--backend",
                "app",
                "launch",
                "--in",
                "t7",
                "--permission-flag",
                "--permission-mode plan",
            ],
            runner,
            clock=runner.clock,
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["permission_mode"], "plan")


class LaunchInputs(unittest.TestCase):
    def test_literal_arguments_and_prompt_are_passed_as_single_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prompt"
            prompt = "hello $(touch /tmp/nope)\nsecond line"
            path.write_text(prompt)
            expected = ["claude", "--permission-mode", "bypassPermissions", "--continue", "space and 'quotes'", "--", prompt]
            command = shlex.join(expected)
            responses = scenario({
                SEND: None,
                ("hc", "send", "t7", command, "--json"): SENT,
                GET: [terminal(), terminal(agent_status("working"))],
                READ: [screen(PROMPT), screen(READY)],
            })
            runner, code, out = launch(responses, "--arg=--continue", "--arg=space and 'quotes'", "--prompt-file", str(path))
            self.assertEqual(code, 0)
            self.assertEqual(shlex.split(out["command"]), expected)
            self.assertEqual(out["status"], "working")
            self.assertEqual(len(runner.ran("hc", "send")), 1)

    def test_missing_prompt_file_fails_before_sending(self):
        runner, code, out = launch({}, "--prompt-file", "/missing/prompt")
        self.assertEqual(code, 2)
        self.assertEqual(out["error"], "prompt_file")
        self.assertEqual(runner.calls, [])

    def test_permission_override_can_omit_default_flags(self):
        command = "claude"
        responses = scenario({
            SEND: None,
            ("hc", "send", "t7", command, "--json"): SENT,
            READ: [screen(PROMPT), screen(BANNER)],
            GET: [terminal(), terminal(agent_status("idle"))],
        })
        _, code, out = launch(responses, "--no-permission-flag")
        self.assertEqual(code, 0)
        self.assertEqual(out["command"], command)
        self.assertIsNone(out["permission_mode"])


class LaunchRefusals(unittest.TestCase):
    def refuse(self, record, table):
        runner = FakeRunner({GET: record, PS: table})
        code, out = run_verb(
            ["--backend", "app", "launch", "--in", "t7"], runner, clock=FakeClock()
        )
        self.assertEqual(runner.ran("hc", "send"), [])
        return code, out

    def test_a_shell_running_a_program_is_not_idle(self):
        code, out = self.refuse(terminal(), SHELL_BUSY)
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "not_idle_shell")
        self.assertIn("vim", out["reason"])

    def test_a_terminal_that_is_not_a_shell_is_not_idle(self):
        code, out = self.refuse(
            terminal(), processes((800, 1, "pts/3", "/opt/agents/claude"))
        )
        self.assertEqual(code, 8)

    def test_a_shell_that_once_reported_a_status_is_refused(self):
        code, out = self.refuse(terminal(reported=True), SHELL_ONLY)
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "reported_shell")

    def test_a_finished_terminal_exits_eleven(self):
        code, _ = self.refuse(terminal(state="finished"), SHELL_ONLY)
        self.assertEqual(code, 11)

    def test_an_unknown_terminal_exits_three(self):
        from support import not_found

        code, _ = self.refuse(not_found(), SHELL_ONLY)
        self.assertEqual(code, 3)

    def test_a_launch_needs_a_place(self):
        code, out = run_verb(["--backend", "app", "launch"], FakeRunner({}))
        self.assertEqual(code, 2)


class LaunchCodex(unittest.TestCase):
    def test_codex_runs_with_no_daemon_in_the_app_and_needs_no_footer(self):
        command = (
            "codex --no-daemon --dangerously-bypass-approvals-and-sandbox "
            "--model gpt-x"
        )
        responses = {
            GET: [terminal(), terminal({"app": "codex", "state": "idle"})],
            PS: [SHELL_ONLY, SHELL_RUNNING],
            READ: [screen(PROMPT), screen("gpt-x xhigh · ~/repo\n")],
            ("hc", "send", "t7", command, "--json"): SENT,
        }
        runner = FakeRunner(responses, clock=FakeClock())
        code, out = run_verb(
            [
                "--backend",
                "app",
                "launch",
                "--in",
                "t7",
                "--agent",
                "codex",
                "--model",
                "gpt-x",
            ],
            runner,
            clock=runner.clock,
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["command"], command)


class LaunchIntoATuiPane(unittest.TestCase):
    def test_runs_the_command_in_the_pane_and_waits_for_the_agent(self):
        command = "claude --permission-mode bypassPermissions"
        info = {"result": {"process_info": {"shell_pid": 800}}}
        pane = lambda status: ok({"result": {"pane": {"agent_status": status}}})
        visible = lambda text: ok({"result": {"read": {"text": text}}})
        runner = FakeRunner(
            {
                PS: [SHELL_ONLY, SHELL_RUNNING],
                ("herdr", "pane", "process-info", "--pane", "w1:p2"): ok(info),
                ("herdr", "pane", "read", "w1:p2", "--source", "visible"): [
                    visible(PROMPT),
                    visible(READY),
                ],
                ("herdr", "pane", "run", "w1:p2", command): ok({}),
                ("herdr", "pane", "get", "w1:p2"): pane("idle"),
            },
            clock=FakeClock(),
        )
        code, out = run_verb(
            ["--backend", "tui", "launch", "--in", "w1:p2"], runner, clock=runner.clock
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["permission_mode"], "bypass")
        self.assertEqual(runner.ran("herdr", "agent"), [])


if __name__ == "__main__":
    unittest.main()
