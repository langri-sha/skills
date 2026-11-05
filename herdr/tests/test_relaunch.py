import tempfile
import unittest
from pathlib import Path

from support import (
    SESSION,
    FakeClock,
    FakeRunner,
    failed,
    ok,
    processes,
    run_verb,
)
from test_launch import BANNER, PROMPT, READY, agent_status, screen

GET = ("hc", "get", "t7", "--json")
READ = ("hc", "read", "t7", "--lines", "0", "--json")
PS = ("ps", "-A", "-o", "pid=,ppid=,tty=,args=")
KEYS = ("hc", "keys", "t7", "ctrl+c", "ctrl+c", "--json")

OLD_AGENT = processes(
    (800, 1, "pts/3", "/usr/bin/bash -i"),
    (810, 800, "pts/3", "/opt/agents/claude --model opus --effort high"),
)
OLD_SHELL = processes((800, 1, "pts/3", "/usr/bin/bash -i"))
TERRAFORM = processes(
    (800, 1, "pts/3", "/usr/bin/bash -i"), (810, 800, "pts/3", "terraform apply")
)
NEW_SHELL = processes((801, 1, "pts/3", "/usr/bin/bash -i"))
NEW_AGENT = processes(
    (801, 1, "pts/3", "/usr/bin/bash -i"),
    (811, 801, "pts/3", "/opt/agents/claude --resume x"),
)

OPUS_READY = READY.replace("Sonnet", "Opus")
RULE = "─" * 20
EMPTY_BOX = f"{RULE}\n❯\xa0\n{RULE}\n  Opus 5.5 · high\n"
TYPED_BOX = f"{RULE}\n❯ half a sentence\n{RULE}\n  Opus 5.5 · high\n"

LABELS = {
    "claude.session": SESSION,
    "claude.model": "opus",
    "claude.effort": "high",
    "claude.cwd": "/tmp/repo",
}


def record(pid=800, reported=True, keep=True, status=None, labels=None, state="live"):
    return ok(
        {
            "address": "t7",
            "pid": pid,
            "keep": keep,
            "reported": reported,
            "state": state,
            "labels": LABELS if labels is None else labels,
            "status": status or agent_status("idle"),
        }
    )


class FakeKill:
    def __init__(self):
        self.calls = []

    def __call__(self, pid, sig):
        self.calls.append((pid, sig))


STATUS = ("herdr-app", "status")
LS = ("herdr-app", "ls")
LAYOUT = ok(
    {
        "spaces": [
            {
                "id": "sp1",
                "name": "Project",
                "tabs": [
                    {
                        "id": "tb1",
                        "name": "Worker",
                        "terminals": [{"terminal": "t7", "pane": "p7"}],
                    }
                ],
            }
        ]
    }
)


def focus(pane):
    return ok({"focused_pane": pane})


def waits():
    return {
        ("hc", "wait", "t7", "--timeout", str(n), "--json", "--output", "herdr-pace-sentinel"): ok({"ended": False})
        for n in range(1, 6)
    } | {
        ("hc", "wait", "t7", "--timeout", str(n), "--json", "--output", "herdr-pace-sentinel"): ok({"ended": False})
        for n in range(1, 6)
    }


def relaunch(responses, *argv):
    clock = FakeClock()
    kill = FakeKill()
    base = {STATUS: focus("p0"), LS: LAYOUT}
    runner = FakeRunner({**waits(), **base, **responses}, clock=clock)
    code, out = run_verb(
        ["--backend", "app", "relaunch", "t7", *argv], runner, clock=clock, kill=kill
    )
    return runner, kill, code, out


RESUME_COMMAND = (
    f"claude --resume {SESSION} --permission-mode bypassPermissions "
    "--model opus --effort high"
)


def resume_scenario():
    return {
        GET: [
            *[record()] * 6,
            record(pid=801, reported=False),
            record(pid=801, reported=False),
            record(pid=801, reported=False, status=agent_status("working")),
            record(pid=801, reported=False),
        ],
        PS: [OLD_AGENT, OLD_AGENT, OLD_SHELL, OLD_SHELL, NEW_SHELL, NEW_AGENT],
        KEYS: ok({}),
        READ: [screen(EMPTY_BOX), screen(PROMPT), screen(PROMPT), screen(OPUS_READY)],
        ("hc", "send", "t7", f"cd /tmp/repo && {RESUME_COMMAND}", "--json"): ok(
            {"started": None, "status": None, "turn": 0}
        ),
    }


class RelaunchWithResume(unittest.TestCase):
    def test_exits_with_ctrl_c_replaces_the_reported_shell_and_resumes_the_session(self):
        runner, kill, code, out = relaunch(resume_scenario(), "--resume")
        self.assertEqual(code, 0)
        self.assertIs(out["exited_agent"], True)
        self.assertIs(out["replaced_shell"], True)
        self.assertIs(out["resumed"], True)
        self.assertEqual(out["command"], RESUME_COMMAND)
        self.assertEqual(out["previous"]["session"], SESSION)
        self.assertEqual(out["permission_mode"], "bypass")
        self.assertEqual(kill.calls[0][0], 800)

    def test_never_sends_exit_through_the_terminal(self):
        runner, _, _, _ = relaunch(resume_scenario(), "--resume")
        sends = [call[3] for call in runner.ran("hc", "send")]
        self.assertTrue(all("/exit" not in text for text in sends))
        self.assertEqual(runner.ran("hc", "keys"), [KEYS])

    def test_a_shell_that_never_reported_is_not_killed(self):
        scenario = resume_scenario()
        scenario[GET] = [
            record(reported=False),
            record(reported=False),
            record(reported=False),
            record(reported=False),
            record(reported=False),
            record(reported=False, status=agent_status("working")),
            record(reported=False),
        ]
        scenario[PS] = [OLD_AGENT, OLD_AGENT, OLD_SHELL, OLD_SHELL, OLD_AGENT]
        _, kill, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 0)
        self.assertEqual(kill.calls, [])
        self.assertIs(out["replaced_shell"], False)

    def test_a_shell_that_cannot_be_replaced_is_refused_before_any_key_is_pressed(self):
        scenario = resume_scenario()
        scenario[GET] = [record(), record(keep=False)]
        runner, kill, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "not_kept")
        self.assertEqual(runner.ran("hc", "keys"), [])
        self.assertEqual(runner.ran("hc", "send"), [])
        self.assertEqual(kill.calls, [])

    def test_a_refusal_comes_before_the_handoff_request_too(self):
        scenario = resume_scenario()
        scenario[GET] = [record(), record(keep=False)]
        runner, _, code, _ = relaunch(scenario, "--resume", "--handoff", "/tmp/never.md")
        self.assertEqual(code, 8)
        self.assertEqual(runner.ran("hc", "send"), [])

    def test_a_focused_terminal_is_held_before_any_key_is_pressed(self):
        scenario = resume_scenario()
        scenario[STATUS] = focus("p7")
        runner, kill, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 13)
        self.assertEqual(out["error"], "held_focus")
        self.assertEqual(runner.ran("hc", "keys"), [])
        self.assertEqual(kill.calls, [])

    def test_a_hold_after_the_exit_says_so_and_carries_what_resuming_needs(self):
        scenario = resume_scenario()
        scenario[STATUS] = [focus("p0"), focus("p7")]
        runner, kill, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 13)
        self.assertEqual(out["error"], "held_focus")
        self.assertIs(out["exited_agent"], True)
        self.assertNotIn("nothing was pressed", out["reason"])
        self.assertEqual(out["previous"]["session"], SESSION)
        self.assertEqual(out["previous"]["kind"], "claude")
        self.assertEqual(out["previous"]["model"], "opus")
        self.assertEqual(out["previous"]["effort"], "high")
        self.assertEqual(out["previous"]["resume"]["command"], RESUME_COMMAND)
        self.assertEqual(kill.calls, [])

    def test_a_session_found_only_in_the_agent_process_is_carried_too(self):
        scenario = resume_scenario()
        scenario[GET] = [record(labels={}) for _ in range(6)]
        scenario[STATUS] = [focus("p0"), focus("p7")]
        scenario[PS] = [
            processes(
                (800, 1, "pts/3", "/usr/bin/bash -i"),
                (810, 800, "pts/3", f"/opt/agents/claude --resume {SESSION} --model opus"),
            ),
            *scenario[PS][1:],
        ]
        _, _, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 13)
        self.assertIs(out["exited_agent"], True)
        self.assertEqual(out["previous"]["session"], SESSION)

    def test_a_busy_shell_after_the_exit_reports_the_exit_and_the_session(self):
        scenario = resume_scenario()
        scenario[PS] = [OLD_AGENT, OLD_AGENT, OLD_SHELL, OLD_AGENT]
        _, kill, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "shell_busy")
        self.assertIs(out["exited_agent"], True)
        self.assertEqual(out["previous"]["session"], SESSION)
        self.assertEqual(kill.calls, [])

    def test_a_shell_that_does_not_come_back_reports_the_exit_and_the_session(self):
        scenario = resume_scenario()
        scenario[GET] = [*[record()] * 7]
        _, kill, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 7)
        self.assertEqual(out["error"], "shell_did_not_return")
        self.assertIs(out["exited_agent"], True)
        self.assertEqual(out["previous"]["session"], SESSION)
        self.assertEqual(len(kill.calls), 1)

    def test_a_failure_before_the_exit_says_the_agent_is_still_running(self):
        scenario = resume_scenario()
        scenario[STATUS] = focus("p7")
        _, _, code, out = relaunch(scenario, "--resume")
        self.assertIs(out["exited_agent"], False)
        self.assertEqual(out["previous"]["session"], SESSION)

    def test_a_launch_failure_after_the_exit_carries_the_session_too(self):
        scenario = resume_scenario()
        scenario[READ] = [
            screen(EMPTY_BOX),
            screen(PROMPT),
            screen(PROMPT),
            screen(PROMPT + "error: authorization timeout\n"),
        ]
        _, _, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 6)
        self.assertIs(out["exited_agent"], True)
        self.assertEqual(out["previous"]["session"], SESSION)

    def test_a_terminal_that_never_reported_is_held_when_focused(self):
        scenario = resume_scenario()
        scenario[GET] = [record(reported=False)]
        scenario[STATUS] = focus("p7")
        runner, kill, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 13)
        self.assertEqual(out["error"], "held_focus")
        self.assertEqual(runner.ran("hc", "keys"), [])
        self.assertEqual(runner.ran("hc", "send"), [])

    def test_text_typed_at_the_prompt_of_a_shell_that_never_reported_is_held(self):
        scenario = resume_scenario()
        scenario[GET] = [record(reported=False)]
        scenario[PS] = [OLD_SHELL]
        scenario[READ] = screen("user@host:~/repo$ git sta\n")
        runner, _, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 13)
        self.assertEqual(out["error"], "held_input")
        self.assertIs(out["exited_agent"], False)
        self.assertEqual(runner.ran("hc", "send"), [])

    def test_text_typed_in_the_agents_input_box_is_held_before_any_key(self):
        scenario = resume_scenario()
        scenario[READ] = screen(TYPED_BOX)
        runner, _, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 13)
        self.assertEqual(out["error"], "held_input")
        self.assertIs(out["exited_agent"], False)
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_the_dimmed_suggestion_in_the_input_box_is_not_typed_text(self):
        for suggestion in (
            'Try "how does .env.example work?"',
            'Try "fix lint errors"',
            'Try "fix typecheck errors"',
        ):
            with self.subTest(suggestion=suggestion):
                scenario = resume_scenario()
                scenario[READ][0] = screen(f"{RULE}\n❯ {suggestion}\n{RULE}\n  Opus 5.5\n")
                _, _, code, _ = relaunch(scenario, "--resume")
                self.assertEqual(code, 0)

    def test_typed_text_that_only_starts_like_a_suggestion_still_holds(self):
        for typed in ('Try "fix lint errors" and then push', "Try fixing it", "fix lint errors"):
            with self.subTest(typed=typed):
                scenario = resume_scenario()
                scenario[READ] = screen(f"{RULE}\n❯ {typed}\n{RULE}\n  Opus 5.5\n")
                runner, _, code, out = relaunch(scenario, "--resume")
                self.assertEqual(code, 13)
                self.assertEqual(runner.ran("hc", "keys"), [])

    def test_an_empty_input_box_does_not_hold_the_agent(self):
        _, _, code, _ = relaunch(resume_scenario(), "--resume")
        self.assertEqual(code, 0)

    def test_a_closed_window_does_not_hold_the_shell(self):
        scenario = resume_scenario()
        scenario[STATUS] = failed(1, text="no window")
        _, kill, code, _ = relaunch(scenario, "--resume")
        self.assertEqual(code, 0)
        self.assertEqual(len(kill.calls), 1)

    def test_text_typed_at_the_prompt_of_an_agentless_shell_is_held(self):
        scenario = resume_scenario()
        scenario[PS] = [OLD_SHELL]
        scenario[READ] = screen("last output\nuser@host:~/repo$ git sta\n")
        runner, kill, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 13)
        self.assertEqual(out["error"], "held_input")
        self.assertEqual(kill.calls, [])
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_an_empty_prompt_does_not_hold_the_shell(self):
        scenario = resume_scenario()
        scenario[PS] = [OLD_SHELL, OLD_SHELL, OLD_SHELL, OLD_SHELL, NEW_SHELL, NEW_AGENT]
        scenario[READ] = [
            screen("user@host:~/repo$ \n"),
            screen(PROMPT),
            screen(PROMPT),
            screen(OPUS_READY),
        ]
        _, kill, code, _ = relaunch(scenario, "--resume")
        self.assertEqual(code, 0)
        self.assertEqual(len(kill.calls), 1)

    def test_a_finished_terminal_reports_finished_without_keys(self):
        runner, kill, code, out = relaunch({GET: record(state="finished"), PS: OLD_SHELL}, "--agent", "claude")
        self.assertEqual(code, 11)
        self.assertEqual(out["error"], "finished")
        self.assertIs(out["exited_agent"], False)
        self.assertEqual(runner.ran("hc", "keys"), [])
        self.assertEqual(kill.calls, [])

    def test_a_program_that_is_not_an_agent_gets_no_keys(self):
        scenario = {GET: record(labels={}, reported=False), PS: TERRAFORM}
        runner, kill, code, out = relaunch(scenario, "--agent", "claude")
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "shell_busy")
        self.assertIs(out["exited_agent"], False)
        self.assertEqual(runner.ran("hc", "keys"), [])
        self.assertEqual(kill.calls, [])

    def test_stale_session_labels_do_not_make_another_program_an_agent(self):
        scenario = {GET: record(), PS: TERRAFORM}
        runner, kill, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "shell_busy")
        self.assertIs(out["exited_agent"], False)
        self.assertEqual(runner.ran("hc", "keys"), [])
        self.assertEqual(kill.calls, [])

    def test_an_agent_that_exited_is_reported_as_exited(self):
        _, _, code, out = relaunch(resume_scenario(), "--resume")
        self.assertEqual(code, 0)
        self.assertIs(out["exited_agent"], True)

    def test_a_shell_with_no_agent_reports_that_none_exited(self):
        scenario = resume_scenario()
        scenario[GET] = [*[record(reported=False)] * 4, record(reported=False, status=agent_status("working")), record(reported=False)]
        scenario[PS] = [OLD_SHELL, OLD_SHELL, OLD_SHELL, OLD_SHELL, OLD_AGENT]
        scenario[READ] = [screen("user@host:~/repo$ \n"), screen(PROMPT), screen(OPUS_READY)]
        runner, _, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 0)
        self.assertIs(out["exited_agent"], False)
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_failures_before_any_key_carry_the_fields_too(self):
        status = agent_status("blocked", kind="question", msg="Sign in? (Yes, No)")
        _, _, code, out = relaunch(
            {GET: record(status=status), PS: OLD_AGENT, READ: screen("")}, "--resume"
        )
        self.assertEqual(code, 9)
        self.assertIs(out["exited_agent"], False)
        self.assertEqual(out["previous"]["session"], SESSION)

    def test_a_terminal_without_a_session_cannot_resume(self):
        scenario = resume_scenario()
        scenario[GET] = [record(labels={})]
        scenario[PS] = [processes((800, 1, "pts/3", "/usr/bin/bash -i"), (810, 800, "pts/3", "/opt/agents/claude"))]
        runner, kill, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "no_session")
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_ctrl_c_that_does_not_exit_the_agent_times_out(self):
        scenario = resume_scenario()
        scenario[PS] = [OLD_AGENT]
        scenario[GET] = [record()]
        runner, kill, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 7)
        self.assertEqual(out["error"], "exit_failed")
        self.assertEqual(len(runner.ran("hc", "keys")), 2)
        self.assertEqual(kill.calls, [])

    def test_a_blocked_agent_is_returned_before_anything_is_pressed(self):
        status = agent_status("blocked", kind="question", msg="Sign in? (Yes, No)")
        scenario = {GET: record(status=status), PS: OLD_AGENT, READ: screen("")}
        runner, _, code, out = relaunch(scenario, "--resume")
        self.assertEqual(code, 9)
        self.assertEqual(out["dialog"]["options"], ["Yes", "No"])
        self.assertEqual(runner.ran("hc", "keys"), [])


class RelaunchSavedSession(unittest.TestCase):
    def test_resumes_the_requested_session_in_an_idle_shell_with_stale_labels(self):
        scenario = resume_scenario()
        scenario[PS] = [OLD_SHELL, OLD_SHELL, OLD_SHELL, OLD_SHELL, NEW_SHELL, NEW_AGENT]
        scenario[READ] = [screen("user@host:~/repo$ \n"), screen(PROMPT), screen(PROMPT), screen(OPUS_READY)]
        command = "claude --resume saved-id --permission-mode bypassPermissions --model opus --effort high"
        scenario.pop(("hc", "send", "t7", f"cd /tmp/repo && {RESUME_COMMAND}", "--json"))
        scenario[("hc", "send", "t7", f"cd /tmp/repo && {command}", "--json")] = ok({})
        _, _, code, out = relaunch(scenario, "--resume-session", "saved-id", "--agent", "claude", "--model", "opus", "--effort", "high")
        self.assertEqual(code, 0)
        self.assertEqual(out["session"], "saved-id")
        self.assertEqual(out["command"], command)
        self.assertIs(out["resumed"], True)

    def test_resumes_a_snapshot_only_session_in_an_idle_tui_pane(self):
        target = "w1:p2"
        command = "codex resume snapshot-id --dangerously-bypass-approvals-and-sandbox --no-alt-screen"
        info = ok({"result": {"process_info": {"shell_pid": 800}}})
        pane = ok({"result": {"pane": {"pane_id": target, "focused": False, "agent_status": "idle"}}})
        visible = lambda text: ok({"result": {"read": {"text": text}}})
        runner = FakeRunner({
            ("herdr", "agent", "get", target): failed(3),
            ("herdr", "pane", "get", target): pane,
            ("herdr", "pane", "process-info", "--pane", target): info,
            ("herdr", "pane", "read", target, "--source", "visible"): [visible(PROMPT), visible(PROMPT), visible("gpt-x high\n")],
            ("herdr", "pane", "run", target, "cd /tmp/repo && " + command): ok({}),
            PS: [OLD_SHELL, OLD_SHELL, OLD_SHELL, OLD_SHELL, OLD_AGENT],
        }, clock=FakeClock())
        code, out = run_verb(["--backend", "tui", "relaunch", target, "--resume-session", "snapshot-id", "--agent", "codex", "--cwd", "/tmp/repo", "--arg=--no-alt-screen"], runner, clock=runner.clock)
        self.assertEqual(code, 0)
        self.assertEqual(out["session"], "snapshot-id")
        self.assertEqual(out["command"], command)
        self.assertEqual(runner.ran("herdr", "agent", "send-keys"), [])

    def test_refuses_to_replace_a_different_live_session(self):
        runner, _, code, out = relaunch(resume_scenario(), "--resume-session", "other", "--agent", "claude")
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "session_mismatch")
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_requires_agent_for_a_saved_session(self):
        runner, _, code, out = relaunch(resume_scenario(), "--resume-session", SESSION)
        self.assertEqual(code, 2)
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_passes_codex_resume_arguments_literally(self):
        scenario = resume_scenario()
        scenario[PS] = [OLD_SHELL, OLD_SHELL, OLD_SHELL, OLD_SHELL, NEW_SHELL, NEW_AGENT]
        scenario[READ] = [screen("user@host:~/repo$ \n"), screen(PROMPT), screen(PROMPT), screen("gpt-x high\n")]
        scenario[GET][-2] = record(pid=801, reported=False, status={"app": "codex", "state": "idle"})
        scenario.pop(("hc", "send", "t7", f"cd /tmp/repo && {RESUME_COMMAND}", "--json"))
        command = "codex resume saved-id --no-daemon --dangerously-bypass-approvals-and-sandbox --model gpt-x --no-alt-screen"
        scenario[("hc", "send", "t7", f"cd /tmp/repo && {command}", "--json")] = ok({})
        _, _, code, out = relaunch(scenario, "--resume-session", "saved-id", "--agent", "codex", "--model", "gpt-x", "--arg=--no-alt-screen")
        self.assertEqual(code, 0)
        self.assertEqual(out["command"], command)


class RelaunchAsAnotherAgent(unittest.TestCase):
    def test_launches_the_new_agent_and_model_without_resuming(self):
        command = (
            "codex --no-daemon --dangerously-bypass-approvals-and-sandbox "
            "--model gpt-x"
        )
        scenario = resume_scenario()
        scenario.pop(("hc", "send", "t7", f"cd /tmp/repo && {RESUME_COMMAND}", "--json"))
        scenario[("hc", "send", "t7", f"cd /tmp/repo && {command}", "--json")] = ok({})
        scenario[GET][-2] = record(pid=801, reported=False, status={"app": "codex", "state": "idle"})
        scenario[READ] = [screen(PROMPT), screen(PROMPT), screen("gpt-x xhigh\n")]
        _, _, code, out = relaunch(scenario, "--agent", "codex", "--model", "gpt-x")
        self.assertEqual(code, 0)
        self.assertEqual(out["command"], command)
        self.assertIs(out["resumed"], False)

    def test_an_agent_cannot_be_resumed_as_another_kind(self):
        _, _, code, out = relaunch(resume_scenario(), "--resume", "--agent", "codex")
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "no_session")


class RelaunchWithAHandoff(unittest.TestCase):
    def scenario(self, path, stops_without_writing=False):
        scenario = resume_scenario()
        request = (
            f"Write a handoff note for the agent that replaces you to {path}: what you "
            "did, what is left, decisions still open, and the files, branches and pull "
            "requests involved. Reply with one line when the file is written."
        )
        scenario[GET] = [
            record(),
            record(),
            record(),
            record(status=agent_status("working")),
            *([record(status=agent_status("idle"))] if stops_without_writing else []),
            *scenario[GET][2:],
        ]
        scenario[("hc", "send", "t7", request, "--json")] = ok(
            {"started": True, "status": "idle", "turn": 3}
        )
        scenario[("hc", "wait", "t7", "--timeout", "30", "--json")] = ok({"ended": True})
        return scenario

    def test_asks_for_the_handoff_and_waits_for_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "handoff.md")

            class Writing(FakeRunner):
                def __call__(self, argv, timeout):
                    if argv[:2] == ["hc", "wait"] and "30" in argv:
                        path.write_text("handoff")
                    return super().__call__(argv, timeout)

            clock = FakeClock()
            base = {STATUS: focus("p0"), LS: LAYOUT}
            runner = Writing(
                {**waits(), **base, **self.scenario(path.resolve())}, clock=clock
            )
            code, out = run_verb(
                ["--backend", "app", "relaunch", "t7", "--resume", "--handoff", str(path)],
                runner,
                clock=clock,
                kill=FakeKill(),
            )
        self.assertEqual(code, 0)
        self.assertEqual(out["handoff"], str(path.resolve()))
        self.assertTrue(runner.ran("hc", "send")[0][3].startswith("Write a handoff note"))

    def test_a_program_replacing_the_agent_during_handoff_gets_no_exit_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "handoff.md")

            class Replacing(FakeRunner):
                replaced = False

                def __call__(self, argv, timeout):
                    if argv[:2] == ["hc", "wait"] and "30" in argv:
                        path.write_text("handoff")
                        self.replaced = True
                    if tuple(argv) == PS and self.replaced:
                        self.calls.append(tuple(argv))
                        return TERRAFORM
                    return super().__call__(argv, timeout)

            clock = FakeClock()
            scenario = self.scenario(path.resolve())
            runner = Replacing({**waits(), STATUS: focus("p0"), LS: LAYOUT, **scenario}, clock=clock)
            code, out = run_verb(
                ["--backend", "app", "relaunch", "t7", "--resume", "--handoff", str(path)],
                runner, clock=clock, kill=FakeKill(),
            )
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "shell_busy")
        self.assertIs(out["exited_agent"], False)
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_an_agent_that_stops_without_the_file_is_reported_and_left_running(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "handoff.md")
            scenario = self.scenario(path.resolve(), stops_without_writing=True)
            runner, _, code, out = relaunch(scenario, "--resume", "--handoff", str(path))
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "handoff_missing")
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_text_typed_while_the_agent_writes_the_handoff_holds_the_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "handoff.md")

            class Writing(FakeRunner):
                def __call__(self, argv, timeout):
                    if argv[:2] == ["hc", "wait"] and "30" in argv:
                        path.write_text("handoff")
                    return super().__call__(argv, timeout)

            scenario = self.scenario(path.resolve())
            scenario[READ] = [screen(EMPTY_BOX), screen(TYPED_BOX)]
            clock = FakeClock()
            base = {STATUS: focus("p0"), LS: LAYOUT}
            runner = Writing({**waits(), **base, **scenario}, clock=clock)
            code, out = run_verb(
                ["--backend", "app", "relaunch", "t7", "--resume", "--handoff", str(path)],
                runner,
                clock=clock,
                kill=FakeKill(),
            )
        self.assertEqual(code, 13)
        self.assertEqual(out["error"], "held_input")
        self.assertEqual(runner.ran("hc", "keys"), [])

    def test_a_handoff_file_that_already_exists_proves_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "handoff.md")
            path.write_text("old")
            runner, _, code, out = relaunch(resume_scenario(), "--resume", "--handoff", str(path))
        self.assertEqual(code, 8)
        self.assertEqual(out["error"], "handoff_exists")
        self.assertEqual(runner.ran("hc", "send"), [])


class RelaunchInTheTui(unittest.TestCase):
    def test_exits_through_agent_keys_and_runs_the_command_in_the_pane(self):
        agent = {
            "pane_id": "w1:p2",
            "name": "rev",
            "agent": "claude",
            "agent_status": "idle",
            "cwd": "/tmp/repo",
            "agent_session": {"agent": "claude", "value": SESSION},
        }
        command = (
            f"claude --resume {SESSION} --permission-mode bypassPermissions "
            "--model opus --effort high"
        )
        info = ok({"result": {"process_info": {"shell_pid": 800}}})
        runner = FakeRunner(
            {
                ("herdr", "agent", "get", "rev"): ok({"result": {"agent": agent}}),
                ("herdr", "pane", "process-info", "--pane", "w1:p2"): info,
                PS: [OLD_AGENT, OLD_AGENT, OLD_SHELL, OLD_SHELL, OLD_AGENT],
                ("herdr", "agent", "send-keys", "w1:p2", "ctrl+c", "ctrl+c"): ok({}),
                ("herdr", "pane", "wait-output", "w1:p2", "--match", "herdr-pace-sentinel", "--timeout", "3000"): ok({}),
                ("herdr", "pane", "read", "w1:p2", "--source", "visible"): [
                    ok({"result": {"read": {"text": PROMPT}}}),
                    ok({"result": {"read": {"text": OPUS_READY}}}),
                ],
                ("herdr", "pane", "run", "w1:p2", f"cd /tmp/repo && {command}"): ok({}),
                ("herdr", "pane", "get", "w1:p2"): ok({"result": {"pane": {"agent_status": "idle"}}}),
            },
            clock=FakeClock(),
        )
        code, out = run_verb(
            ["--backend", "tui", "relaunch", "rev", "--resume"], runner, clock=runner.clock
        )
        self.assertEqual(code, 0)
        self.assertIs(out["replaced_shell"], False)
        self.assertEqual(out["address"], "w1:p2")

    def test_a_pane_that_gains_focus_during_the_exit_is_not_typed_into(self):
        agent = {
            "pane_id": "w1:p2",
            "name": "rev",
            "agent": "claude",
            "agent_status": "idle",
            "cwd": "/tmp/repo",
            "agent_session": {"agent": "claude", "value": SESSION},
        }
        info = ok({"result": {"process_info": {"shell_pid": 800}}})
        pane = lambda focused: ok(
            {"result": {"pane": {"agent_status": "idle", "focused": focused}}}
        )
        runner = FakeRunner(
            {
                ("herdr", "agent", "get", "rev"): ok({"result": {"agent": agent}}),
                ("herdr", "pane", "process-info", "--pane", "w1:p2"): info,
                PS: [OLD_AGENT, OLD_AGENT, OLD_SHELL],
                ("herdr", "agent", "send-keys", "w1:p2", "ctrl+c", "ctrl+c"): ok({}),
                ("herdr", "pane", "read", "w1:p2", "--source", "visible"): ok(
                    {"result": {"read": {"text": PROMPT}}}
                ),
                ("herdr", "pane", "get", "w1:p2"): [pane(False), pane(True)],
            },
            clock=FakeClock(),
        )
        code, out = run_verb(
            ["--backend", "tui", "relaunch", "rev", "--resume"], runner, clock=runner.clock
        )
        self.assertEqual(code, 13)
        self.assertEqual(out["error"], "held_focus")
        self.assertIs(out["exited_agent"], True)
        self.assertEqual(runner.ran("herdr", "pane", "run"), [])

    def test_a_focused_pane_is_held_before_any_key(self):
        agent = {"pane_id": "w1:p2", "agent": "claude", "agent_status": "idle"}
        runner = FakeRunner(
            {
                ("herdr", "agent", "get", "rev"): ok({"result": {"agent": agent}}),
                ("herdr", "pane", "process-info", "--pane", "w1:p2"): ok(
                    {"result": {"process_info": {"shell_pid": 800}}}
                ),
                PS: OLD_AGENT,
                ("herdr", "pane", "get", "w1:p2"): ok(
                    {"result": {"pane": {"focused": True}}}
                ),
            }
        )
        code, out = run_verb(["--backend", "tui", "relaunch", "rev"], runner)
        self.assertEqual(code, 13)
        self.assertIs(out["exited_agent"], False)
        self.assertEqual(runner.ran("herdr", "agent", "send-keys"), [])


if __name__ == "__main__":
    unittest.main()
