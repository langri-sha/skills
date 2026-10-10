---
name: critique
user_invocable: true
description: >-
  Start a critique watcher in a tmux split pane to review local changes
metadata:
  author: langri-
  version: '1.0.0'
---

# critique

Start a critique watcher in a tmux split pane.

## Workflow

### 1. Check for tmux

Detect whether the current process is running inside a tmux pane by checking the
`$TMUX` and `$TMUX_PANE` environment variables:

```bash
if [ -z "$TMUX" ] || [ -z "$TMUX_PANE" ]; then
  echo "Not inside a tmux pane. Start tmux first, then retry /critique."
  exit 1
fi
```

Check both variables: the split targets `$TMUX_PANE`, and an empty target
(`-t ""`) silently resolves to the user's focused window instead of failing.

### 2. Working Directory

Pass `$PWD` inline in the split command. Do not capture `CWD=$(pwd)` in a
separate step — shell variables don't survive across separate Bash tool
invocations, and `-c ""` silently starts the pane in the wrong directory.

### 3. Create Vertical Split and Start Critique

Split the calling window horizontally (creates a vertical split on the right)
and run `critique --watch origin/main` in the new pane. Target `$TMUX_PANE`
explicitly — a bare `split-window` follows the window the user is currently
focused on, which may not be the one this agent runs in — and use `:?` so an
unset pane fails loudly rather than falling back to the focused window:

```bash
tmux split-window -t "${TMUX_PANE:?}" -h -c "$PWD" "critique --watch origin/main"
```

### 4. Output Summary

```
Critique watcher started!

  Pane: vertical split (right)
  Directory: <cwd>
  Command: critique --watch origin/main
```
