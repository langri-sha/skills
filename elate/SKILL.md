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

The shared Herdr launcher reports a blocked dialog, failed launcher, or timeout
with the terminal address and state. On failure the script retains the startup
prompt file and prints a recovery command. Check the agent screen and, in the
app, its turn count before using it; send only after confirming the prompt was
not submitted. Only the folder-trust dialog may be answered through the Herdr
skill's `dialog` verb. Other dialogs need the user. A failed start leaves the
created terminal or pane available for inspection.

Report the agent's pane, or in the Herdr app its terminal, and in the Herdr app
and TUI the agent name, then stop. Do not interact with the new pane — the agent
is now driving it independently.
