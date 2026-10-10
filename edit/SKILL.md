---
name: edit
user_invocable: true
description: >-
  Open an editor in the current worktree — nvim in a tmux split by default, or a
  named editor (e.g. zed, code, cursor) as a standalone process
metadata:
  author: langri-
  version: '1.0.0'
---

# edit

Open an editor in the current worktree.

- **`/edit`** (no args) — open `nvim` in a right-hand tmux split pane.
- **`/edit <command>`** — launch `<command> .` as a standalone process (e.g.
  `/edit zed`, `/edit code`, `/edit cursor`).

## Workflow

### 1. Working Directory

The editor must open in the current worktree. Use `$PWD` inline in the launch
commands — do not capture `CWD=$(pwd)` in a separate step, because shell
variables don't survive across separate Bash tool invocations, and an empty
`-c ""` silently opens the editor in the wrong directory.

### 2. Dispatch on Argument

If no argument is provided, take the tmux split path. Otherwise, validate the
editor command and launch it as a standalone process.

### 3a. Default Path (nvim in tmux split)

When invoked with no argument, require a tmux pane and open `nvim` in a
right-hand split. Target `$TMUX_PANE` explicitly — a bare `split-window` follows
the window the user is currently focused on, which may not be the one this agent
runs in — and guard both variables, since an empty target (`-t ""`) silently
resolves to the focused window instead of failing:

```bash
if [ -z "$TMUX" ] || [ -z "$TMUX_PANE" ]; then
  echo "Not inside a tmux pane. Start tmux first, then retry /edit."
  exit 1
fi

tmux split-window -t "${TMUX_PANE:?}" -h -c "$PWD" "nvim"
```

Then output:

```
Editor started!

  Pane: vertical split (right)
  Directory: <cwd>
  Command: nvim
```

### 3b. Named Editor Path

When invoked with an argument, resolve the command — expanding a shell alias to
its real target — and launch it against the current directory. Do not require
tmux. Surface launch errors instead of swallowing them.

```bash
EDITOR_CMD="<arg>"

# Resolve the editor word before launching.
#
# Bash expands aliases only for *literal* command words, never when the command
# name comes from a variable — so `"$EDITOR_CMD" .` execs a literal `zed` and
# fails on hosts where `zed` is an alias (e.g. `alias zed='zeditor'`). The old
# `command -v "$EDITOR_CMD"` guard hid this: it *succeeds* for an alias, so the
# doomed launch passed the check and then no-op'd behind `&`.
#
# We classify the word with `type` and expand an alias to its real command line
# via `BASH_ALIASES`. Tradeoff vs the alternatives:
#   - `bash -ic '<cmd> .'` lets bash expand the alias natively, but the editor
#     name must be spliced into the string as a literal (passing it via a var
#     hits the same bug), and interactive bash emits job-control noise on a
#     non-tty. More fragile, so avoided.
#   - A hardcoded zed->zeditor map doesn't generalize. Avoided.
# This relies on the shell having the user's aliases loaded — it does: the
# profile is sourced and `expand_aliases` is on.
case "$(type -t "$EDITOR_CMD" 2>/dev/null)" in
  alias) LAUNCH="${BASH_ALIASES[$EDITOR_CMD]}" ;;
  file | function | builtin | keyword) LAUNCH="$EDITOR_CMD" ;;
  *) echo "Editor command not found: $EDITOR_CMD"; exit 1 ;;
esac

# Launch in the background so this skill returns, but do NOT swallow startup
# errors. Capture stderr, then probe the process: if it died immediately
# (missing binary, bad args) report its stderr and exit non-zero; if it is still
# alive (foreground editor) or detached cleanly (exit 0), treat it as launched.
# $LAUNCH is left unquoted on purpose: an alias body may carry flags (e.g.
# `zeditor --foo`) that must word-split into command + arguments.
LOG=$(mktemp "/tmp/edit-launch-XXXXXX.log")
( cd "$PWD" && exec $LAUNCH . ) >/dev/null 2>"$LOG" &
EDITOR_PID=$!

sleep 0.3
if kill -0 "$EDITOR_PID" 2>/dev/null; then
  STATUS=0
else
  wait "$EDITOR_PID"
  STATUS=$?
fi

if [ "$STATUS" -ne 0 ]; then
  echo "Editor failed to launch ($EDITOR_CMD -> $LAUNCH, exit $STATUS):"
  cat "$LOG"
  rm -f "$LOG"
  exit "$STATUS"
fi
rm -f "$LOG"
```

Then output:

```
Editor started!

  Directory: <cwd>
  Command: <launch> .
```
