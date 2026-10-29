---
name: elate
user_invocable: true
description: >-
  Spin up a parallel codex agent in a vertical split, in tmux or Herdr. Splits
  the current window (tmux) or the dispatcher's pane (Herdr), launches `codex`
  in the new pane, and seeds it with a prompt telling it to read the dispatcher
  pane's contents and treat them as its brief. Optional argument is appended to
  the seed prompt as extra context.
metadata:
  author: langri-sha
  version: '1.0.1'
---

# elate

Hand the current pane's context to a parallel `codex` agent in a fresh tmux or
Herdr split.

## Arguments

| Argument | Default | Description                                                       |
| -------- | ------- | ----------------------------------------------------------------- |
| `extra`  | empty   | Optional extra context appended to the codex seed prompt verbatim |

If invoked without an argument, codex reads pane 1 only. If an argument is
given, it is included in the seed prompt so codex has both the pane contents and
the dispatcher's note.

Codex runs with the model and reasoning effort from `~/.codex/config.toml`. In
Herdr the agent is named `elate-<dispatcher pane id>`, lowercased, with `-2`,
`-3`, … appended while a live agent already holds the name.

## Workflow

### 1. Detect the Multiplexer

Herdr sets `HERDR_ENV` and `HERDR_PANE_ID`, tmux sets `TMUX` and `TMUX_PANE`,
and when one runs inside the other the agent inherits both sets. `HERDR_*` also
goes stale when a pane moves. The variables only name candidates: the agent
belongs to the multiplexer whose pane terminal is its controlling terminal. A
tool shell often has no terminal of its own, so take the nearest ancestor's.

Herdr's own record of the agent in a pane can't settle this: an agent started in
tmux inside Herdr reports its session to the inherited outer pane.

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
if [ "$MUX" = none ]; then
  echo "Not in a tmux or Herdr pane of this agent's own. Start one first, then retry /elate."
  exit 1
fi
```

A match proves the pane variable names this agent's own pane; for Herdr, `PANE`
is its live ID even after a move. A sandbox that hides parent processes or the
multiplexer's socket also ends in `none`; rerun the step outside it.

### 2. Resolve the Brief Pane and CWD

`BRIEF_PANE` is the pane codex reads; `BRIEF_WHERE` describes it in the seed
prompt.

**tmux.** Resolve the calling window's id, the first pane's id, and the working
directory. Use `$TMUX_PANE` (set by tmux on the calling shell) so the skill
targets the user's window, not whatever pane happens to be active on the tmux
server. Reference panes by `@id`/`%id` so the skill is independent of
`base-index` or `pane-base-index`.

```bash
WINDOW_ID=$(tmux display-message -p -t "$TMUX_PANE" '#{window_id}')
FIRST_PANE_ID=$(tmux list-panes -t "$WINDOW_ID" -F '#{pane_id}' | head -1)
CWD=$(pwd)

BRIEF_PANE=$FIRST_PANE_ID
BRIEF_WHERE="tmux pane $FIRST_PANE_ID of the same window"

echo "Window:     $WINDOW_ID"
echo "First pane: $FIRST_PANE_ID"
echo "Directory:  $CWD"
```

**Herdr.** The brief is the dispatcher pane, the one step 1 confirmed is this
session's. Never choose a pane from another tab: the codex pane must land in the
tab the user is looking at.

```bash
DISPATCHER_PANE=$PANE
CWD=$(pwd)

BRIEF_PANE=$DISPATCHER_PANE
BRIEF_WHERE="Herdr pane $DISPATCHER_PANE, next to your own"

BASE="elate-$(printf '%s' "$DISPATCHER_PANE" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9_-' '-')"
LIVE=$(herdr agent list | jq -r '.result.agents[].name // empty')
AGENT_NAME=$BASE
N=2
while grep -qx "$AGENT_NAME" <<<"$LIVE"; do
  AGENT_NAME="$BASE-$N"
  N=$((N + 1))
done

echo "Dispatcher pane: $DISPATCHER_PANE"
echo "Agent name:      $AGENT_NAME"
echo "Directory:       $CWD"
```

### 3. Build the Seed Prompt

Build the prompt as a shell variable. Reference the resolved brief pane so codex
reads the right pane.

```bash
EXTRA="${EXTRA:-}"  # populated from the optional skill argument

if [ "$MUX" = herdr ]; then
  READ_BRIEF="herdr pane read $BRIEF_PANE --source recent-unwrapped --lines 400"
  READ_MORE="For more scrollback, raise \`--lines\`."
else
  READ_BRIEF="tmux capture-pane -t $BRIEF_PANE -p"
  READ_MORE="For more scrollback, pass \`-S -\` to capture from the start of history."
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
```

### 4. Split, Launch Codex

**tmux.** Hand the prompt to the new pane via `-e` (an environment variable) so
the new pane's shell can pass it to codex without any quoting hazards. Split
horizontally for a right-hand pane, then even out the window.

```bash
tmux split-window -t "$WINDOW_ID" -h -c "$CWD" \
  -e "ELATE_PROMPT=$ELATE_PROMPT" \
  'codex "$ELATE_PROMPT"'
tmux select-layout -t "$WINDOW_ID" even-horizontal
```

The shell command is single-quoted so `$ELATE_PROMPT` expands in the new pane,
not in the calling shell. Because the prompt travels through the environment
rather than the command line, backticks, `$(...)`, and stray quotes inside it
stay literal — no shell ever re-parses the prompt body.

**Herdr.** Split the dispatcher pane to the right without moving focus, start
codex in the new pane, then seed it. `agent start` needs a shell prompt, which a
fresh split provides; `agent prompt` takes the text as one argument, so the
prompt body is never re-parsed either.

```bash
CODEX_PANE=$(herdr pane split --pane "$DISPATCHER_PANE" --direction right \
  --cwd "$CWD" --no-focus | jq -r '.result.pane.pane_id')
[ -n "$CODEX_PANE" ] && [ "$CODEX_PANE" != null ] || { echo "Split failed."; exit 1; }

herdr agent start "$AGENT_NAME" --kind codex --pane "$CODEX_PANE" --timeout 60000
herdr agent prompt "$AGENT_NAME" "$ELATE_PROMPT"
```

If `agent start` returns `agent_not_ready`, codex is blocked at startup, usually
on the folder-trust dialog. Read it with
`herdr agent read "$AGENT_NAME" --source visible`, show it to the user, and let
them answer it. Seed the prompt once `herdr agent get "$AGENT_NAME"` reports
`idle`.

### 5. Output Summary

```
Elate launched!

  Window:        <window>            (Herdr: tab <tab-id>)
  Source pane:   <first-pane-id>     (Herdr: dispatcher pane)
  Codex pane:    vertical split (right)   (Herdr: <codex-pane>, agent <name>)
  Directory:     <cwd>
```

STOP after launching. Do not interact with the new pane — codex is now driving
it independently.

## Edge Cases

### Not Inside tmux or Herdr

Bail in step 1 with a hint to start one of them.

### Inherited Pane Is Not This Agent's

A background job, a session nested in another multiplexer, or a terminal opened
from a pane can inherit a pane ID that is not its own. Step 1 then picks the
multiplexer that owns this agent's terminal, or stops with `none`; ask which
pane is the conversation instead of splitting a guess.

### Window Already Has Many Panes

tmux: `select-layout even-horizontal` rebalances every pane in the window, so
the new codex pane joins existing splits as an equal slice. Herdr: only the
dispatcher pane is halved; other panes keep their size.

### Model or Effort Requested

The argument is brief text, not codex settings. To override the model or effort
for one launch, add `-m <model>` or `-c model_reasoning_effort="<effort>"` to
the codex command: after `--` in `herdr agent start`, or before the prompt in
the tmux `codex` command.

### Codex Not on PATH

tmux: the split still opens, but the shell command exits immediately and the
pane closes. Herdr: `agent start` fails and leaves a bare shell pane. Either
way, confirm `codex` resolves (`command -v codex`) before reporting elate
launched.
