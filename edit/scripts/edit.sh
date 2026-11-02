#!/usr/bin/env bash
# Opens an editor in the working directory. With no arguments, nvim in a split
# right of this agent's own tmux, Herdr app or Herdr TUI pane; with a command,
# "<command> ." as a standalone process.
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

HERDR_SCRIPT=$(dirname "$(realpath "${BASH_SOURCE[0]}")")/../../herdr/scripts/herdr.py
SEAT=$(python3 "$HERDR_SCRIPT" seat) || {
  echo "$SEAT" >&2
  exit 1
}
if [ "$(jq -r '.session_match' <<<"$SEAT")" = false ]; then
  echo "This terminal belongs to another session; ask which terminal to use." >&2
  exit 1
fi
MUX=$(jq -r '.backend' <<<"$SEAT")
PANE= MUX_TERMINAL=
case $MUX in
  tmux) PANE=$(jq -r '.target' <<<"$SEAT") ;;
  app) MUX_TERMINAL=$(jq -r '.target' <<<"$SEAT") ;;
  tui) MUX=herdr; PANE=$(jq -r '.target' <<<"$SEAT") ;;
esac
echo "multiplexer=$MUX pane=$PANE terminal=$MUX_TERMINAL"

case $MUX in
tmux)
  # An empty target resolves to the focused window, so fail instead.
  tmux split-window -t "${TMUX_PANE:?}" -h -c "$PWD" nvim
  ;;
app)
  PANE=$(herdr-app ls | jq -r --arg t "${MUX_TERMINAL:?}" \
    '.spaces[].tabs[].terminals[] | select(.terminal == $t) | .pane // empty')
  : "${PANE:?no pane for this terminal, or the Herdr app window is closed}"
  # pane.split has no directory argument and would use the pane's current
  # folder, so env -C pins the worktree. The program runs bare, with no shell,
  # and the pane closes when it exits.
  SPLIT=$(herdr-app do pane.split --pane "$PANE" --direction right \
    --argv "$(jq -cn --arg d "$PWD" '["env", "-C", $d, "nvim"]')")
  EDITOR_TERMINAL=$(jq -r '.terminal // empty' <<<"$SPLIT")
  : "${EDITOR_TERMINAL:?split failed: $SPLIT}"
  echo "editor terminal=$EDITOR_TERMINAL dir=$PWD"
  ;;
herdr)
  EDITOR_PANE=$(herdr pane split --pane "$PANE" --direction right --cwd "$PWD" --no-focus |
    jq -r '.result.pane.pane_id // empty')
  : "${EDITOR_PANE:?split failed}"
  # Wait for the shell's prompt, so nvim isn't typed into a shell still starting.
  herdr pane wait-output "$EDITOR_PANE" --source visible --regex '\S' --timeout 10000 >/dev/null
  herdr pane run "$EDITOR_PANE" nvim
  echo "editor pane=$EDITOR_PANE dir=$PWD"
  ;;
*)
  echo "This agent is not in a tmux, Herdr app or Herdr TUI pane of its own." >&2
  exit 1
  ;;
esac
