---
name: edit
user_invocable: true
description: >-
  Open an editor in the current worktree — nvim in a tmux or Herdr split by
  default, or a named editor (e.g. zed, code, cursor) as a standalone process
metadata:
  author: langri-
  version: '1.1.0'
---

# edit

Open an editor in the current worktree.

- **`/edit`** (no args) — open `nvim` in a right-hand tmux or Herdr split pane.
- **`/edit <command>`** — launch `<command> .` as a standalone process (e.g.
  `/edit zed`, `/edit code`, `/edit cursor`).

## Workflow

`<skill-dir>` is this skill's directory. Run the script from the current
worktree: it opens the editor in its working directory.

### nvim in a split

With no argument:

```bash
bash <skill-dir>/scripts/edit.sh
```

It splits this agent's own pane to the right, in whichever of tmux or Herdr owns
this agent's terminal, and starts nvim there. When neither does, it says so and
exits 1; a named editor still works. A sandbox that hides parent processes or
the multiplexer's socket ends the same way, so rerun it outside the sandbox. The
tmux pane closes when nvim exits; the Herdr pane keeps its shell.

Report the directory and, in Herdr, the new pane's ID.

### A named editor

The script runs without your shell's aliases, so expand an alias first, then
pass the command:

```bash
EDITOR_CMD=<arg>
[ "$(type -t "$EDITOR_CMD")" = alias ] && EDITOR_CMD=${BASH_ALIASES[$EDITOR_CMD]}
bash <skill-dir>/scripts/edit.sh $EDITOR_CMD
```

`$EDITOR_CMD` stays unquoted so an alias's flags split into arguments. The
script launches `<command> .` in the background, without needing a multiplexer,
and reports a launch that fails at once with its stderr.

Report the directory and the command launched.
