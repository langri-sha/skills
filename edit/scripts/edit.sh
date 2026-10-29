#!/usr/bin/env bash
# Opens an editor in the working directory. With no arguments, nvim in a split
# right of this agent's own tmux or Herdr pane; with a command, "<command> ." as
# a standalone process.
#
# Usage: edit.sh [command [args...]]

set -u

if [ "$#" -gt 0 ]; then
  if ! command -v "$1" >/dev/null; then
    echo "Editor command not found: $1" >&2
    exit 1
  fi
  # Launch in the background so the script returns, then report a launch that
  # dies at once with its stderr. A foreground editor still running, or one that
  # detached with status 0, has launched.
  log=$(mktemp "${TMPDIR:-/tmp}/edit-launch-XXXXXX.log")
  "$@" . >/dev/null 2>"$log" &
  pid=$!
  sleep 0.3
  if kill -0 "$pid" 2>/dev/null; then
    status=0
  else
    wait "$pid"
    status=$?
  fi
  if [ "$status" -ne 0 ]; then
    echo "Editor failed to launch ($*, exit $status):" >&2
    cat "$log" >&2
  else
    echo "launched: $* . in $PWD"
  fi
  rm -f "$log"
  exit "$status"
fi

# The pane variables only name candidates: when one multiplexer runs inside the
# other, both sets are inherited. The caller belongs to the multiplexer whose
# pane terminal is its controlling terminal, the nearest ancestor's when this
# process has none.
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

case $MUX in
tmux)
  # An empty target resolves to the focused window, so fail instead.
  tmux split-window -t "${TMUX_PANE:?}" -h -c "$PWD" nvim
  ;;
herdr)
  EDITOR_PANE=$(herdr pane split --current --direction right --cwd "$PWD" --no-focus |
    jq -r '.result.pane.pane_id // empty')
  : "${EDITOR_PANE:?split failed}"
  # Wait for the shell's prompt, so nvim isn't typed into a shell still starting.
  herdr pane wait-output "$EDITOR_PANE" --source visible --regex '\S' --timeout 10000 >/dev/null
  herdr pane run "$EDITOR_PANE" nvim
  echo "editor pane=$EDITOR_PANE dir=$PWD"
  ;;
*)
  echo "This agent is not in a tmux or Herdr pane of its own." >&2
  exit 1
  ;;
esac
