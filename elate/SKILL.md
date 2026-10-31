---
name: elate
description: >-
  Starts a parallel agent, codex or Claude Code, in a split beside this agent's
  tmux, Herdr app or Herdr TUI pane, seeded to read that pane as its brief, with
  any extra context appended. Use when asked to elate, or to hand the
  conversation to a parallel agent. Not for a new worktree session
  (create-session).
disable-model-invocation: true
metadata:
  author: langri-sha
  version: '1.2.1'
---

# elate

Hand the current pane's context to a parallel `codex` or `claude` agent in a
fresh tmux, Herdr app or Herdr TUI split.

The optional argument may open with an agent or model, then an effort, which
pick what runs; the rest is extra context, appended verbatim to the agent's seed
prompt. Without extra context, the agent reads only the brief pane: the window's
first pane in tmux, this agent's own terminal in the Herdr app, its own pane in
the Herdr TUI. In the Herdr app and TUI the agent is named
`elate-<dispatcher terminal or pane id>`, lowercased, with `-2`, `-3`, …
appended while a live agent already holds the name.

## Agent, model and effort

Turn the named agent or model into options for the script:

| Named                                              | Options                      |
| -------------------------------------------------- | ---------------------------- |
| `claude` or Claude Code alone                      | `--agent claude`             |
| `codex`, `sol`, or nothing                         | none: codex on `gpt-6.1-sol` |
| any other model, such as `opus` or `gpt-5.6-terra` | `--model <model>`            |

The script starts claude for a Claude model, such as `opus` or `claude-…`,
matched regardless of case, and codex for any other, and prints the model and
effort it picked.

An effort word, `low`, `medium`, `high`, `xhigh` or `max`, or `ultra` for codex,
becomes `--effort <word>` when it follows the agent or model, or is the whole
argument. Without one, codex runs at `xhigh` and claude at its configured
effort. So "opus xhigh" is `--model opus --effort xhigh`.

## Launch

`<skill-dir>` is this skill's directory. Run the script from the directory the
agent should work in, with the options from the table:

```bash
bash <skill-dir>/scripts/elate.sh [--agent claude] [--model <model>] [--effort <effort>]
```

With extra context, add `-` and pass the context on stdin, so no shell parses
it:

```bash
bash <skill-dir>/scripts/elate.sh [options] - <<'ELATE_EXTRA'
<the extra context, verbatim>
ELATE_EXTRA
```

The script finds the multiplexer that owns this agent's terminal, opens a pane
beside this agent's own without moving focus, and starts the agent there through
the user's shell, with a prompt telling it to read the brief pane and treat it
as the user's instructions. It prints the agent's pane, or in the Herdr app its
terminal's address, and in the Herdr app and TUI the agent name. In the Herdr
app codex runs with `--no-daemon`, so its commands stay in its own terminal, and
the launch needs the app window to be open.

Other flags for the agent go after `--`, and only when the user names them;
never one that takes several values, such as claude's `--add-dir`, since it
would take the prompt as one more.

## When it stops

- **Not in a pane of its own:** outside tmux, the Herdr app and the Herdr TUI,
  ask the user to start one and retry. Inside one, a background job, a session
  nested in another multiplexer, or a terminal opened from a pane can inherit a
  pane or terminal ID that isn't its own: ask which pane is the conversation
  instead of splitting a guess. A sandbox that hides parent processes or a
  multiplexer's socket ends the same way; rerun the script outside it.
- **`blocked` in the Herdr app, exit 3:** the agent is at a dialog, usually
  folder trust. Read it with `hc read <name>`, show it to the user and let them
  answer it. The agent keeps the prompt it was started with, and its composer
  empties when it submits, so run the seed command the script printed only if
  `hc get <name> --json` still shows `turn: 0` once the agent is idle.
- **No status or `error` in the Herdr app, exit 1:** the agent reported nothing
  within the wait, or an error. The screen printed after the launch line says
  why: an `op` approval still pending, a start that failed and left a bare
  shell, or the agent's own error, such as a model it doesn't know. Show it to
  the user; the terminal stays, and an approved agent goes on with its prompt.
- **`agent_not_ready` in the Herdr TUI, exit 3:** the agent is blocked at
  startup, usually on the folder-trust dialog. Read it with
  `herdr agent read <name> --source visible`, show it to the user and let them
  answer it. Once `herdr agent get <name>` reports `idle`, run the seed command
  the script printed.
- **Anything else,** such as the agent missing from `PATH` or an option the
  script refuses: report the error. A failed Herdr TUI start leaves a bare shell
  in the printed pane, and so does a failed tmux start, without an error.

Report the agent's pane, or in the Herdr app its terminal, and in the Herdr app
and TUI the agent name, then stop. Do not interact with the new pane — the agent
is now driving it independently.
