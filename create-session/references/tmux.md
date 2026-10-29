# tmux procedure

Use the backend, lane, slug, cwd, and quoted assistant command resolved in
`SKILL.md`. The snippets below use `SESSION_LANE`, `SESSION_SLUG`,
`SESSION_CWD`, and `SESSION_COMMAND` for those values. Keep dependent commands
in one shell invocation or carry their captured IDs explicitly between calls.

## Create

For caller lane inheritance, query only the validated pane:

```bash
tmux display-message -p -t "${TMUX_PANE:?}" '#{session_name}'
```

Use `=` for exact session names. When targeting `dev`, migrate the legacy
session `0` only if `dev` does not exist:

```bash
if [ "$SESSION_LANE" = dev ] && ! tmux has-session -t '=dev' 2>/dev/null &&
  tmux has-session -t '=0' 2>/dev/null; then
  tmux rename-session -t '=0' dev || exit 1
fi
```

Create a shell window and capture stable window and pane IDs. The empty window
component in `=<lane>:` appends at the next unused index. Detached creation
keeps the caller's focus and starts the server when necessary.

```bash
if tmux has-session -t "=$SESSION_LANE" 2>/dev/null; then
  SESSION_CREATED=$(tmux new-window -d -t "=$SESSION_LANE:" \
    -n "$SESSION_SLUG" -c "$SESSION_CWD" -P -F '#{window_id} #{pane_id}') || exit 1
else
  SESSION_CREATED=$(tmux new-session -d -s "$SESSION_LANE" \
    -n "$SESSION_SLUG" -c "$SESSION_CWD" -P -F '#{window_id} #{pane_id}') || exit 1
fi
read -r SESSION_WINDOW SESSION_LEFT <<< "$SESSION_CREATED"
: "${SESSION_WINDOW:?}" "${SESSION_LEFT:?}"

SESSION_RIGHT=$(tmux split-window -d -t "$SESSION_LEFT" -h \
  -c "$SESSION_CWD" -P -F '#{pane_id}' \
  'critique --watch origin/main') || exit 1
tmux select-layout -t "$SESSION_WINDOW" even-horizontal || exit 1
tmux send-keys -t "$SESSION_LEFT" -l -- "$SESSION_COMMAND" || exit 1
tmux send-keys -t "$SESSION_LEFT" Enter || exit 1
```

## Move a window

Require an explicit destination lane. Resolve a named window by exact name
across all sessions, or validate an explicit stable window ID. List candidates
with their session names when the name is ambiguous:

```bash
tmux list-windows -a -F '#{window_id} #{session_name}:#{window_name}'
```

With no window argument, resolve the caller's window from its validated pane:

```bash
SESSION_WINDOW=$(tmux display-message -p -t "${TMUX_PANE:?}" '#{window_id}') || exit 1
```

From outside tmux, require an explicit window. Reject an empty or ambiguous
window ID before passing it to a mutation; an empty target can resolve to
unrelated focused work. Never move a window from the long-lived `letta` session
through this lane workflow.

```bash
: "${SESSION_WINDOW:?}"
SESSION_SOURCE=$(tmux display-message -p -t "$SESSION_WINDOW" '#{session_name}') || exit 1
if [ "$SESSION_SOURCE" = letta ]; then
  echo 'The letta session is outside the lane system' >&2
  exit 1
fi
if [ "$SESSION_SOURCE" = "$SESSION_LANE" ]; then
  echo "Window already in $SESSION_LANE"
  exit 0
fi

SESSION_PLACEHOLDER=''
if ! tmux has-session -t "=$SESSION_LANE" 2>/dev/null; then
  SESSION_PLACEHOLDER=$(tmux new-session -d -s "$SESSION_LANE" \
    -P -F '#{window_id}') || exit 1
fi
tmux move-window -d -s "$SESSION_WINDOW" -t "=$SESSION_LANE:" || exit 1
if [ -n "$SESSION_PLACEHOLDER" ]; then
  tmux kill-window -t "$SESSION_PLACEHOLDER" || exit 1
fi
```

Moving preserves the entire window and its running panes. tmux destroys a lane
when its final window leaves; it can be created again on demand.
