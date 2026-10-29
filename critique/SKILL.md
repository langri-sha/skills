---
name: critique
description: >-
  Opens a critique watcher that reviews local changes, in a split beside this
  agent's tmux or Herdr pane. Use when asked to start critique or to watch the
  working changes. Not for a new worktree session with its own watcher
  (create-session).
metadata:
  author: langri-
  version: '1.1.0'
---

# critique

Start a critique watcher in a split pane, in tmux or Herdr.

## Workflow

### 1. Detect the Multiplexer

Herdr sets `HERDR_ENV` and `HERDR_PANE_ID`, tmux sets `TMUX` and `TMUX_PANE`,
and when one runs inside the other the agent inherits both sets. The variables
only name candidates: the agent belongs to the multiplexer whose pane terminal
is its controlling terminal. A tool shell often has no terminal of its own, so
take the nearest ancestor's.

```bash
tty=
pid=$$
while [ "${pid:-1}" -gt 1 ]; do
  t=$(ps -o tty= -p "$pid" | tr -d ' ')
  case $t in '' | '?' | '??') pid=$(ps -o ppid= -p "$pid" | tr -d ' ') ;; *) tty=/dev/$t && break ;; esac
done
MUX=none PANE=
if [ -n "$tty" ] && [ -n "${TMUX_PANE:-}" ] &&
  [ "$(tmux display-message -p -t "$TMUX_PANE" '#{pane_tty}' 2>/dev/null)" = "$tty" ]; then
  MUX=tmux PANE=$TMUX_PANE
elif [ -n "$tty" ] && [ "${HERDR_ENV:-}" = 1 ] && [ -n "${HERDR_PANE_ID:-}" ] &&
  INFO=$(herdr pane process-info --current 2>/dev/null) &&
  [ "/dev/$(ps -o tty= -p "$(jq -r '.result.process_info.shell_pid' <<<"$INFO")" 2>/dev/null | tr -d ' ')" = "$tty" ]; then
  MUX=herdr PANE=$(jq -r '.result.process_info.pane_id' <<<"$INFO")
fi
echo "multiplexer=$MUX pane=$PANE"
```

A match proves the pane variable names this agent's own pane, so later steps can
target `$TMUX_PANE` or Herdr's `--current`, which resolves a moved pane's
inherited ID to its live one. With `none`, say this agent is not in a tmux or
Herdr pane and stop. A sandbox that hides parent processes or the multiplexer's
socket also ends here; rerun the step outside it.

### 2. Working Directory

Pass `$PWD` inline in the split command. Do not capture `CWD=$(pwd)` in a
separate step — shell variables don't survive across separate Bash tool
invocations, and an empty directory silently starts the pane in the wrong place.

### 3. Create Vertical Split and Start Critique

**tmux.** Split the calling window horizontally (creates a vertical split on the
right) and run `critique --watch origin/main` in the new pane. Target
`$TMUX_PANE` explicitly — a bare `split-window` follows the window the user is
currently focused on, which may not be the one this agent runs in — and use `:?`
so an unset pane fails loudly rather than falling back to the focused window:

```bash
tmux split-window -t "${TMUX_PANE:?}" -h -c "$PWD" "critique --watch origin/main"
```

The pane closes when critique exits.

**Herdr.** Split to the right without moving the user's focus, wait for the new
shell to draw its prompt so the command isn't typed into a shell still starting
up, then run critique in it. `herdr pane --help` has the installed syntax.

```bash
CRITIQUE_PANE=$(herdr pane split --current --direction right --cwd "$PWD" --no-focus |
  jq -r '.result.pane.pane_id // empty')
: "${CRITIQUE_PANE:?split failed}"
herdr pane wait-output "$CRITIQUE_PANE" --source visible --regex '\S' --timeout 10000 >/dev/null
herdr pane run "$CRITIQUE_PANE" 'critique --watch origin/main'
```

The pane keeps its shell after critique exits.

Report the directory and, in Herdr, the new pane's ID.
