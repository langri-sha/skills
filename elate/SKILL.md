---
name: elate
description: >-
  Starts a parallel codex agent in a split beside this agent's tmux, Herdr app
  or Herdr TUI pane, seeded to read that pane as its brief, with any extra
  context appended. Use when asked to elate, or to hand the conversation to a
  parallel codex agent. Not for a new worktree session (create-session).
disable-model-invocation: true
metadata:
  author: langri-sha
  version: '1.1.0'
---

# elate

Hand the current pane's context to a parallel `codex` agent in a fresh tmux,
Herdr app or Herdr TUI split.

The optional argument is extra context, appended verbatim to codex's seed
prompt. Without one, codex reads only the brief pane: the window's first pane in
tmux, this agent's own terminal in the Herdr app, its own pane in the Herdr TUI.
Codex runs with the model and reasoning effort from `~/.codex/config.toml`. In
the Herdr app and TUI the agent is named
`elate-<dispatcher terminal or pane id>`, lowercased, with `-2`, `-3`, …
appended while a live agent already holds the name.

## Launch

`<skill-dir>` is this skill's directory. Run the script from the directory codex
should work in. Without an argument:

```bash
bash <skill-dir>/scripts/elate.sh
```

With one, pass it on stdin, so no shell parses it:

```bash
bash <skill-dir>/scripts/elate.sh - <<'ELATE_EXTRA'
<the argument, verbatim>
ELATE_EXTRA
```

The script finds the multiplexer that owns this agent's terminal, opens a pane
beside this agent's own without moving focus, and starts codex there with a
prompt telling it to read the brief pane and treat it as the user's
instructions. It prints the codex pane, or in the Herdr app the codex terminal's
address, and in the Herdr app and TUI the agent name. In the Herdr app codex
runs with `--no-daemon`, so its commands stay in its own terminal, and the
launch needs the app window to be open.

The argument is brief text, not codex settings. To override the model or effort
for one launch, put codex flags after `--`, such as
`-- -m <model> -c model_reasoning_effort="<effort>"`.

## When it stops

- **Not in a pane of its own:** outside tmux, the Herdr app and the Herdr TUI,
  ask the user to start one and retry. Inside one, a background job, a session
  nested in another multiplexer, or a terminal opened from a pane can inherit a
  pane or terminal ID that isn't its own: ask which pane is the conversation
  instead of splitting a guess. A sandbox that hides parent processes or a
  multiplexer's socket ends the same way; rerun the script outside it.
- **`blocked` in the Herdr app, exit 3:** codex is at a dialog, usually folder
  trust. Read it with `hc read <name>`, show it to the user and let them answer
  it. Codex keeps the prompt it was started with, and its composer empties when
  it submits, so run the seed command the script printed only if
  `hc get <name> --json` still shows `turn: 0` once codex is idle.
- **No status in the Herdr app, exit 1:** codex reported nothing within the
  wait. The screen printed after the launch line says why: an `op` approval
  still pending, or a start that failed and left a bare shell. Show it to the
  user; the terminal stays, and an approved codex goes on with its prompt.
- **`agent_not_ready` in the Herdr TUI, exit 3:** codex is blocked at startup,
  usually on the folder-trust dialog. Read it with
  `herdr agent read <name> --source visible`, show it to the user and let them
  answer it. Once `herdr agent get <name>` reports `idle`, run the seed command
  the script printed.
- **Anything else,** such as codex missing from `PATH`: report the error. A
  failed Herdr TUI start leaves a bare shell in the printed pane.

Report the codex pane, or in the Herdr app its terminal, and in the Herdr app
and TUI the agent name, then stop. Do not interact with the new pane — codex is
now driving it independently.
