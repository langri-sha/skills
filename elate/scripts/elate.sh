#!/usr/bin/env bash
# Starts a parallel codex agent in a split right of this agent's own tmux or
# Herdr pane, seeded to read the brief pane: the window's first pane in tmux,
# this agent's own pane in Herdr. Run it from the directory codex should work
# in.
#
# Usage: elate.sh [-] [-- codex-args...]
#   -   append extra context from stdin to the seed prompt

set -u

EXTRA=
if [ "${1:-}" = - ]; then
  EXTRA=$(cat)
  shift
fi
[ "${1:-}" = -- ] && shift

# The pane variables only name candidates: when one multiplexer runs inside the
# other, both sets are inherited, and HERDR_* goes stale when a pane moves.
# Herdr's own record of the agent in a pane can't settle it either, since an
# agent started in tmux inside Herdr reports to the outer pane. The caller
# belongs to the multiplexer whose pane terminal is its controlling terminal,
# the nearest ancestor's when this process has none.
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
if [ "$MUX" = none ]; then
  echo "Not in a tmux or Herdr pane of this agent's own." >&2
  exit 1
fi

CWD=$PWD

if [ "$MUX" = tmux ]; then
  # Panes are addressed by ID, so base-index settings don't matter.
  WINDOW_ID=$(tmux display-message -p -t "$TMUX_PANE" '#{window_id}')
  BRIEF_PANE=$(tmux list-panes -t "$WINDOW_ID" -F '#{pane_id}' | head -1)
  BRIEF_WHERE="tmux pane $BRIEF_PANE of the same window"
  READ_BRIEF="tmux capture-pane -t $BRIEF_PANE -p"
  READ_MORE="For more scrollback, pass \`-S -\` to capture from the start of history."
else
  BRIEF_PANE=$PANE
  BRIEF_WHERE="Herdr pane $BRIEF_PANE, next to your own"
  READ_BRIEF="herdr pane read $BRIEF_PANE --source recent-unwrapped --lines 400"
  READ_MORE="For more scrollback, raise \`--lines\`."

  BASE="elate-$(printf '%s' "$BRIEF_PANE" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9_-' '-')"
  LIVE=$(herdr agent list | jq -r '.result.agents[].name // empty')
  AGENT_NAME=$BASE
  N=2
  while grep -qx "$AGENT_NAME" <<<"$LIVE"; do
    AGENT_NAME="$BASE-$N"
    N=$((N + 1))
  done
fi

ELATE_PROMPT="You are a parallel codex agent launched via the /elate skill.

Another agent (Claude Code, or a human) is working in $BRIEF_WHERE.
That pane is your brief.

Steps:

1. Run \`$READ_BRIEF\` to read the dispatcher pane's contents.
   $READ_MORE
2. Treat the captured text as the user's instructions and follow them. Pay
   attention to recent prompts, plans, file paths, and error output.
3. Operate from the working directory \`$CWD\`.

If the captured pane is ambiguous, ask one clarifying question before acting."

if [ -n "$EXTRA" ]; then
  ELATE_PROMPT="$ELATE_PROMPT

Additional context from the dispatcher:

$EXTRA"
fi

if [ "$MUX" = tmux ]; then
  # The pane's shell runs codex without the caller's functions or aliases.
  command -v codex >/dev/null || {
    echo "codex is not on PATH." >&2
    exit 1
  }
  # The prompt travels in the environment and expands in the new pane, so no
  # shell re-parses its backticks, $(...) or quotes.
  CODEX=codex
  [ "$#" -gt 0 ] && CODEX="codex $(printf '%q ' "$@")"
  CODEX_PANE=$(tmux split-window -t "$WINDOW_ID" -h -c "$CWD" -P -F '#{pane_id}' \
    -e "ELATE_PROMPT=$ELATE_PROMPT" "$CODEX \"\$ELATE_PROMPT\"") || exit 1
  tmux select-layout -t "$WINDOW_ID" even-horizontal
  echo "codex pane=$CODEX_PANE brief=$BRIEF_PANE window=$WINDOW_ID dir=$CWD"
  exit 0
fi

CODEX_PANE=$(herdr pane split --pane "$BRIEF_PANE" --direction right \
  --cwd "$CWD" --no-focus | jq -r '.result.pane.pane_id // empty')
[ -n "$CODEX_PANE" ] || {
  echo "Split failed." >&2
  exit 1
}
echo "codex pane=$CODEX_PANE agent=$AGENT_NAME brief=$BRIEF_PANE dir=$CWD"

# agent start needs the shell prompt a fresh split provides.
[ "$#" -gt 0 ] && set -- -- "$@"
if ! OUT=$(herdr agent start "$AGENT_NAME" --kind codex --pane "$CODEX_PANE" \
  --timeout 60000 "$@" 2>&1); then
  echo "$OUT" >&2
  if [ "$(jq -r '.error.code // empty' <<<"$OUT" 2>/dev/null)" = agent_not_ready ]; then
    PROMPT_FILE=$(mktemp "${TMPDIR:-/tmp}/elate-prompt-XXXXXX")
    printf '%s' "$ELATE_PROMPT" >"$PROMPT_FILE"
    echo "codex is blocked at startup; seed it once it is idle with:" >&2
    echo "herdr agent prompt $AGENT_NAME \"\$(cat $PROMPT_FILE)\"" >&2
    exit 3
  fi
  exit 1
fi
# The prompt is one argument, so no shell re-parses it.
herdr agent prompt "$AGENT_NAME" "$ELATE_PROMPT"
