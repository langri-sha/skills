---
name: lights-out
user_invocable: true
description: >-
  Safely close the tmux window this agent session lives in — last one out turns
  off the lights. Use when the user says "/lights-out", "kill this window",
  "close this window", or wants the agent to clean up its own tmux window after
  wrapping up. Always targets the agent's own pane explicitly; never runs bare
  tmux kill commands.
metadata:
  author: langri-sha
  version: '1.0.0'
---

# lights-out

Close the tmux window this session lives in — safely, and only this one.

## Why this skill exists

Bare tmux commands (`tmux kill-window` with no `-t`) resolve to the **attached
client's focused window** — whatever the user is looking at — not the window
containing this agent's pane, even when `TMUX_PANE` is set in the environment. A
bare kill once took out the wrong window while the user was focused elsewhere.
Destructive tmux commands must always carry an explicit target.

## Workflow

### 1. Pre-flight

Run these checks before killing anything. If any check fails, STOP and tell the
user — never fall back to a bare command or guess a target.

Resolve the target window from this session's own pane:

```bash
: "${TMUX:?not inside tmux}" "${TMUX_PANE:?no pane id}"
tmux list-panes -t "$TMUX_PANE" >/dev/null || { echo "pane $TMUX_PANE is gone"; exit 1; }
tmux display-message -p -t "$TMUX_PANE" 'closing: #S:#I #W (#{window_id})'
```

Each guard covers a distinct failure that would otherwise be silent:

- `${TMUX_PANE:?}` — an empty target (`-t ""`) resolves to the user's focused
  window, the exact bug this skill exists to prevent.
- `${TMUX:?}` — without `$TMUX` the client falls back to the default socket,
  where the same `%N` can name an unrelated pane on the wrong server.
- `list-panes` — `display-message` exits 0 with empty output for a vanished
  pane, so it cannot serve as the existence check; `list-panes` genuinely fails.

Never substitute a window index (`-t 0:10`) — indexes renumber; only the pane id
(`%N`) and window id (`@N`) are stable.

### 2. Check for Unfinished Business

- `git status --porcelain` — uncommitted changes?
- `git rev-parse --abbrev-ref '@{u}'` — no upstream means the branch was never
  pushed: treat that as pending, then `git log '@{u}..' --oneline` for unpushed
  commits when an upstream exists.
- Running background tasks, monitors, or workflows in this session?

If anything is pending, report it and ask before proceeding (unless the user
already told you to close regardless).

### 3. Announce

State the window name/id being closed, so the user can object if it isn't what
they expect. Say goodbye **before** the kill — it terminates this agent's
process, so nothing after it will run, and no farewell message can follow it.

### 4. Kill

As the very last tool call of the turn:

```bash
tmux kill-window -t "${TMUX_PANE:?}"
```

A pane target resolves to its containing window, so this takes the whole window
— including sibling panes like a critique watcher — with it.

## Never

- Never run `kill-window`, `kill-pane`, `kill-session`, or `respawn-*` without
  an explicit `-t`.
- Never target by window index.
- Never `kill-session` or `kill-server` — the blast radius is every other window
  the user has open.
