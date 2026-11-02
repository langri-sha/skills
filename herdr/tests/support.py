import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "herdr.py"

spec = importlib.util.spec_from_file_location("herdr_script", SCRIPT)
herdr = importlib.util.module_from_spec(spec)
sys.modules["herdr_script"] = herdr
spec.loader.exec_module(herdr)

SESSION = "11111111-2222-3333-4444-555555555555"
OTHER_SESSION = "99999999-8888-7777-6666-000000000000"


def ok(payload=""):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return herdr.Result(0, text, "")


def failed(code=1, payload=None, text=""):
    err = json.dumps(payload) if payload is not None else text
    return herdr.Result(code, "", err)


def not_found(message="no terminal"):
    return failed(3, {"error": {"kind": "not_found", "message": message}})


def screen(text):
    return ok({"complete": True, "how": "screen", "text": text})


def agent_status(state, **extra):
    return {"app": "claude-code", "state": state, **extra}


def processes(*rows):
    return ok(
        "".join(f"{pid:>7} {ppid:>7} {tty:<8} {args}\n" for pid, ppid, tty, args in rows)
    )


class FakeClock:
    def __init__(self):
        self.seconds = 0.0

    def __call__(self):
        return self.seconds

    def advance(self, seconds):
        self.seconds += seconds


def waited_seconds(key):
    if key[:2] == ("hc", "wait") and "--timeout" in key:
        return float(key[key.index("--timeout") + 1])
    if key[:3] == ("herdr", "pane", "wait-output") and "--timeout" in key:
        return float(key[key.index("--timeout") + 1]) / 1000
    return 0.0


class FakeRunner:
    def __init__(self, responses, clock=None):
        self.responses = dict(responses)
        self.calls = []
        self.clock = clock

    def __call__(self, argv, timeout):
        key = tuple(argv)
        self.calls.append(key)
        if self.clock:
            self.clock.advance(waited_seconds(key))
        if key not in self.responses:
            raise AssertionError(f"unexpected command: {key}")
        reply = self.responses[key]
        if isinstance(reply, list):
            return reply.pop(0) if len(reply) > 1 else reply[0]
        return reply

    def ran(self, *prefix):
        return [call for call in self.calls if call[: len(prefix)] == prefix]


def run_verb(argv, runner, environ=None, pid=902, home=None, clock=None):
    system = herdr.System(
        runner=runner,
        environ=environ or {},
        pid=pid,
        home=home or "/nonexistent",
        clock=clock,
        which=lambda name: f"/usr/bin/{name}",
    )
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            code = herdr.run(argv, system)
        except SystemExit as stop:
            code = stop.code
    lines = out.getvalue().splitlines()
    return code, json.loads(lines[-1]) if lines else None


PS = ("ps", "-A", "-o", "pid=,ppid=,tty=,args=")

SESSION_PROCESSES = processes(
    (800, 1, "pts/3", "-bash"),
    (900, 800, "pts/3", "/opt/agents/claude --model opus"),
    (901, 900, "?", "/bin/bash -c eval"),
    (902, 901, "?", "python3 herdr.py"),
)
