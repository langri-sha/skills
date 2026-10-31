---
name: edit
description: >-
  Opens an editor on the current worktree: nvim in a split beside this agent's
  tmux, Herdr app or Herdr TUI pane, or a named editor such as zed, code or
  cursor as its own process. Use when asked to open the worktree in an editor.
  Not for watching the diff (critique).
metadata:
  author: langri-
  version: '1.2.0'
---

# edit

Open an editor in the current worktree.

- **`/edit`** (no args) — open `nvim` in a right-hand tmux, Herdr app or Herdr
  TUI split pane.
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

It splits this agent's own pane to the right, in whichever of tmux, the Herdr
app or the Herdr TUI owns this agent's terminal, and starts nvim there. When
none does, it says so and exits 1; a named editor still works. A sandbox that
hides parent processes or a multiplexer's socket ends the same way, so rerun it
outside the sandbox. In the Herdr app the split does not move the user's focus
and needs the app window to be open. The tmux and Herdr app panes close when
nvim exits; the Herdr TUI pane keeps its shell.

Report the directory and, in the Herdr app, the new terminal's address, or in
the Herdr TUI, the new pane's ID.

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
