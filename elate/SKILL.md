---
name: elate
user_invocable: true
description: >-
  Spin up a parallel codex agent in a vertical split, in tmux or Herdr. Splits
  the current window (tmux) or the dispatcher's pane (Herdr), launches `codex`
  in the new pane, and seeds it with a prompt telling it to read the dispatcher
  pane's contents and treat them as its brief. Optional argument is appended to
  the seed prompt as extra context.
disable-model-invocation: true
metadata:
  author: langri-sha
  version: '1.0.1'
---

# elate

Hand the current pane's context to a parallel `codex` agent in a fresh tmux or
Herdr split.

The optional argument is extra context, appended verbatim to codex's seed
prompt. Without one, codex reads only the brief pane: the window's first pane in
tmux, this agent's own pane in Herdr. Codex runs with the model and reasoning
effort from `~/.codex/config.toml`. In Herdr the agent is named
`elate-<dispatcher pane id>`, lowercased, with `-2`, `-3`, … appended while a
live agent already holds the name.

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

The script finds the multiplexer that owns this agent's terminal, splits to the
right without moving focus, and starts codex with a prompt telling it to read
the brief pane and treat it as the user's instructions. It prints the codex pane
and, in Herdr, the agent name.

The argument is brief text, not codex settings. To override the model or effort
for one launch, put codex flags after `--`, such as
`-- -m <model> -c model_reasoning_effort="<effort>"`.

## When it stops

- **Not in a pane of its own:** outside tmux and Herdr, ask the user to start
  one and retry. Inside one, a background job, a session nested in another
  multiplexer, or a terminal opened from a pane can inherit a pane ID that isn't
  its own: ask which pane is the conversation instead of splitting a guess. A
  sandbox that hides parent processes or the multiplexer's socket ends the same
  way; rerun the script outside it.
- **`agent_not_ready` in Herdr, exit 3:** codex is blocked at startup, usually
  on the folder-trust dialog. Read it with
  `herdr agent read <name> --source visible`, show it to the user and let them
  answer it. Once `herdr agent get <name>` reports `idle`, run the seed command
  the script printed.
- **Anything else,** such as codex missing from `PATH`: report the error. A
  failed Herdr start leaves a bare shell in the printed pane.

Report the codex pane, and in Herdr the agent name, then stop. Do not interact
with the new pane — codex is now driving it independently.
