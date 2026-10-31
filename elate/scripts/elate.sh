#!/usr/bin/env bash
# Starts a parallel claude or codex agent beside this agent's own tmux, Herdr
# app or Herdr TUI pane, seeded to read the brief: the window's first pane in
# tmux, this agent's own terminal in the app, its own pane in the TUI. Run it
# from the directory the agent should work in.
#
# Usage: elate.sh [--agent claude|codex] [--model <model>] [--effort <level>]
#                 [-] [-- agent-args...]
#   --agent   the CLI to start; without it, claude for a Claude model name and
#             codex otherwise
#   --model   its model, gpt-6.1-sol for codex by default
#   --effort  claude's --effort, or codex's model_reasoning_effort, xhigh for
#             codex by default
#   -         append extra context from stdin to the seed prompt

set -u

AGENT='' MODEL='' EFFORT='' EXTRA=''
while [ "$#" -gt 0 ]; do
  case $1 in
  --agent) AGENT=${2:?--agent needs a value} && shift ;;
  --model) MODEL=${2:?--model needs a value} && shift ;;
  --effort) EFFORT=${2:?--effort needs a value} && shift ;;
  -) EXTRA=$(cat) ;;
  --) shift && break ;;
  *)
    echo "Unknown option: $1" >&2
    exit 2
    ;;
  esac
  shift
done
if [ -z "$AGENT" ]; then
  case $MODEL in
  opus* | sonnet* | haiku* | fable* | best | opusplan | claude-*) AGENT=claude ;;
  *) AGENT=codex ;;
  esac
fi
case $AGENT in
claude) LEVELS='low medium high xhigh max' ;;
codex)
  LEVELS='low medium high xhigh max ultra'
  MODEL=${MODEL:-gpt-6.1-sol} EFFORT=${EFFORT:-xhigh}
  ;;
*)
  echo "--agent is claude or codex, not '$AGENT'." >&2
  exit 2
  ;;
esac
if [ -n "$EFFORT" ] && [[ " $LEVELS " != *" $EFFORT "* ]]; then
  echo "--effort for $AGENT is one of: $LEVELS." >&2
  exit 2
fi
if [ -n "$EFFORT" ] && [ "$AGENT" = claude ]; then
  set -- --effort "$EFFORT" "$@"
elif [ -n "$EFFORT" ]; then
  set -- -c "model_reasoning_effort=\"$EFFORT\"" "$@"
fi
[ -n "$MODEL" ] && set -- --model "$MODEL" "$@"
PICKED="model=${MODEL:-default} effort=${EFFORT:-default}"

# The variables only name candidates: when one multiplexer runs inside another,
# every set is inherited, and HERDR_* goes stale when a pane moves. Herdr's own
# record of the agent in a pane can't settle it either, since an agent started
# in tmux inside Herdr reports to the outer pane. The caller belongs to the
# multiplexer whose terminal is its controlling terminal, the nearest
# ancestor's when this process has none.
tty=
pid=$$
while [ "${pid:-1}" -gt 1 ]; do
  t=$(ps -o tty= -p "$pid" | tr -d ' ')
  case $t in '' | '?' | '??') pid=$(ps -o ppid= -p "$pid" | tr -d ' ') ;; *) tty=/dev/$t && break ;; esac
done
MUX=none PANE= MUX_TERMINAL=
if [ -n "$tty" ] && [ -n "${TMUX_PANE:-}" ] &&
  [ "$(tmux display-message -p -t "$TMUX_PANE" '#{pane_tty}' 2>/dev/null)" = "$tty" ]; then
  MUX=tmux PANE=$TMUX_PANE
elif [ -n "$tty" ] && [ -n "${HC_TERMINAL_ID:-}" ] &&
  INFO=$(hc get "$HC_TERMINAL_ID" --json 2>/dev/null) &&
  [ "/dev/$(ps -o tty= -p "$(jq -r '.pid // empty' <<<"$INFO")" 2>/dev/null | tr -d ' ')" = "$tty" ]; then
  MUX=app MUX_TERMINAL=$HC_TERMINAL_ID
elif [ -n "$tty" ] && [ "${HERDR_ENV:-}" = 1 ] && [ -n "${HERDR_PANE_ID:-}" ] &&
  INFO=$(herdr pane process-info --current 2>/dev/null) &&
  [ "/dev/$(ps -o tty= -p "$(jq -r '.result.process_info.shell_pid' <<<"$INFO")" 2>/dev/null | tr -d ' ')" = "$tty" ]; then
  MUX=herdr PANE=$(jq -r '.result.process_info.pane_id' <<<"$INFO")
fi
echo "multiplexer=$MUX pane=$PANE terminal=$MUX_TERMINAL"
if [ "$MUX" = none ]; then
  echo "Not in a tmux, Herdr app or Herdr TUI pane of this agent's own." >&2
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
elif [ "$MUX" = app ]; then
  # INFO is this terminal's hc record from detection. The tab comes from the
  # app, since a terminal placed by its space label alone carries no tab label.
  SPACE=$(jq -r '.labels["herdr.space"] // empty' <<<"$INFO")
  LS=$(herdr-app ls) || {
    echo "The Herdr app window is not open." >&2
    exit 1
  }
  TAB=$(jq -r --arg t "$MUX_TERMINAL" \
    '.spaces[].tabs[] | select(any(.terminals[]; .terminal == $t)) | .id' <<<"$LS")
  if [ -z "$SPACE" ] || [ -z "$TAB" ]; then
    echo "Terminal $MUX_TERMINAL has no pane of its own." >&2
    exit 1
  fi
  BRIEF_WHERE="Herdr app terminal $MUX_TERMINAL, next to your own"
  READ_BRIEF="hc read $MUX_TERMINAL --lines 400"
  READ_MORE="For more scrollback, raise \`--lines\`. If the read ends with \`[hc] only its screen\`, run \`hc wait $MUX_TERMINAL\`, then read again."

  BASE="elate-$(printf '%s' "$MUX_TERMINAL" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9_-' '-')"
  LIVE=$(hc ls --json) || {
    [ -n "$LIVE" ] && echo "$LIVE" >&2
    exit 1
  }
  LIVE=$(jq -r '.terminals[].name // empty' <<<"$LIVE")
  AGENT_NAME=$BASE
  N=2
  while grep -qx "$AGENT_NAME" <<<"$LIVE"; do
    AGENT_NAME="$BASE-$N"
    N=$((N + 1))
  done
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

ELATE_PROMPT="You are a parallel agent launched via the /elate skill.

Another agent (Claude Code, or a human) is working in $BRIEF_WHERE.
That pane is your brief.

Steps:

1. Run \`$READ_BRIEF\` to read the dispatcher pane's contents.
   $READ_MORE
2. Treat the captured text as the user's instructions and follow them. Pay
   attention to recent prompts, plans, file paths, and error output.
3. Operate from the working directory \`$CWD\`.

The latest /elate request on that screen is the one that started you: don't run
elate or start other agents unless the brief asks for that explicitly.

If the captured pane is ambiguous, ask one clarifying question before acting."

if [ -n "$EXTRA" ]; then
  ELATE_PROMPT="$ELATE_PROMPT

Additional context from the dispatcher:

$EXTRA"
fi

# The wrapper runs the agent in an interactive shell, so the user's functions
# apply, and leaves that shell behind when the agent exits. The prompt travels
# as one argument, so no shell re-parses it. shortcut: it reaches only a bash
# user's functions; use $SHELL if a zsh or fish user needs theirs.
WRAP=("$BASH" -ic '"$@"; exec "$0" -i' "$BASH")

if [ "$MUX" = tmux ]; then
  # This checks the caller's PATH; the pane resolves the agent after ~/.bashrc.
  command -v "$AGENT" >/dev/null || {
    echo "$AGENT is not on PATH." >&2
    exit 1
  }
  # tmux execs a command of several words as given, without a shell.
  # shortcut: nothing waits for a status here, so a pending op approval or a
  # failed start still prints success; add a wait if quiet failures show up.
  AGENT_PANE=$(tmux split-window -t "$WINDOW_ID" -h -c "$CWD" -P -F '#{pane_id}' -- \
    "${WRAP[@]}" "$AGENT" "$@" "$ELATE_PROMPT") || exit 1
  tmux select-layout -t "$WINDOW_ID" even-horizontal
  echo "$AGENT pane=$AGENT_PANE $PICKED brief=$BRIEF_PANE window=$WINDOW_ID dir=$CWD"
  exit 0
fi

if [ "$MUX" = app ]; then
  # The labels place the terminal in this tab without moving focus; with no
  # parent, the agent neither ends with the dispatcher nor types notes into it.
  # --no-daemon keeps codex's commands in its own terminal; it goes before the
  # user's flags so none can displace it.
  [ "$AGENT" = codex ] && set -- --no-daemon "$@"
  OUT=$(hc run --bg --no-parent --keep --json \
    --name "$AGENT_NAME" --cwd "$CWD" \
    --label herdr.space="$SPACE" --label herdr.tab="$TAB" -- \
    "${WRAP[@]}" "$AGENT" "$@" "$ELATE_PROMPT") || {
    [ -n "$OUT" ] && echo "$OUT" >&2
    exit 1
  }
  AGENT_TERMINAL=$(jq -r '.address // empty' <<<"$OUT")
  echo "$AGENT terminal=$AGENT_TERMINAL $PICKED agent=$AGENT_NAME brief=$MUX_TERMINAL dir=$CWD"
  # A status other than error proves the agent is running. None within the
  # wait means op is still waiting for its approval, or the agent never started
  # and the wrapper's shell sits there; the screen says which.
  WAIT=$(timeout 30 hc wait "$AGENT_TERMINAL" --timeout 10 --json) || {
    [ -n "$WAIT" ] && echo "$WAIT" >&2
    exit 1
  }
  STATUS=$(jq -r '.status // empty' <<<"$WAIT")
  if [ "$STATUS" = blocked ]; then
    PROMPT_FILE=$(mktemp "${TMPDIR:-/tmp}/elate-prompt-XXXXXX")
    printf '%s' "$ELATE_PROMPT" >"$PROMPT_FILE"
    echo "$AGENT is blocked at startup; if \`hc get $AGENT_NAME --json\` still shows turn 0 once it is idle, seed it with:" >&2
    echo "hc send $AGENT_NAME \"\$(cat $PROMPT_FILE)\"" >&2
    exit 3
  fi
  if [ -z "$STATUS" ] || [ "$STATUS" = error ]; then
    echo "$AGENT reported ${STATUS:-no status}; its screen:" >&2
    hc read "$AGENT_TERMINAL" --lines 20 >&2
    exit 1
  fi
  exit 0
fi

AGENT_PANE=$(herdr pane split --pane "$BRIEF_PANE" --direction right \
  --cwd "$CWD" --no-focus | jq -r '.result.pane.pane_id // empty')
[ -n "$AGENT_PANE" ] || {
  echo "Split failed." >&2
  exit 1
}
echo "$AGENT pane=$AGENT_PANE $PICKED agent=$AGENT_NAME brief=$BRIEF_PANE dir=$CWD"

# agent start needs the shell prompt a fresh split provides.
[ "$#" -gt 0 ] && set -- -- "$@"
if ! OUT=$(herdr agent start "$AGENT_NAME" --kind "$AGENT" --pane "$AGENT_PANE" \
  --timeout 60000 "$@" 2>&1); then
  echo "$OUT" >&2
  if [ "$(jq -r '.error.code // empty' <<<"$OUT" 2>/dev/null)" = agent_not_ready ]; then
    PROMPT_FILE=$(mktemp "${TMPDIR:-/tmp}/elate-prompt-XXXXXX")
    printf '%s' "$ELATE_PROMPT" >"$PROMPT_FILE"
    echo "$AGENT is blocked at startup; seed it once it is idle with:" >&2
    echo "herdr agent prompt $AGENT_NAME \"\$(cat $PROMPT_FILE)\"" >&2
    exit 3
  fi
  exit 1
fi
# The prompt is one argument, so no shell re-parses it.
herdr agent prompt "$AGENT_NAME" "$ELATE_PROMPT"
