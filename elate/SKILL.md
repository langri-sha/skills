---
name: elate
user_invocable: true
description: >-
  Spin up a parallel codex agent in a vertical tmux split. Splits the current
  window evenly, launches `codex` in the new pane, and seeds it with a prompt
  telling it to capture pane 1's contents and treat them as its brief. Optional
  argument is appended to the seed prompt as extra context.
metadata:
  author: langri-sha
  version: '1.0.0'
---

# elate

Hand the current pane's context to a parallel `codex` agent in a fresh tmux
split.

## Arguments

| Argument | Default | Description                                                       |
| -------- | ------- | ----------------------------------------------------------------- |
| `extra`  | empty   | Optional extra context appended to the codex seed prompt verbatim |

If invoked without an argument, codex reads pane 1 only. If an argument is
given, it is included in the seed prompt so codex has both the pane contents and
the dispatcher's note.

## Workflow

### 1. Check for tmux

```bash
if [ -z "$TMUX" ]; then
  echo "Not inside a tmux session. Start tmux first, then retry /elate."
  exit 1
fi
```

### 2. Resolve Window, First Pane, and CWD

Resolve the calling window's id, the first pane's id, and the working directory.
Use `$TMUX_PANE` (set by tmux on the calling shell) so the skill targets the
user's window, not whatever pane happens to be active on the tmux server.
Reference panes by `@id`/`%id` so the skill is independent of `base-index` or
`pane-base-index`.

```bash
WINDOW_ID=$(tmux display-message -p -t "$TMUX_PANE" '#{window_id}')
FIRST_PANE_ID=$(tmux list-panes -t "$WINDOW_ID" -F '#{pane_id}' | head -1)
CWD=$(pwd)

echo "Window:     $WINDOW_ID"
echo "First pane: $FIRST_PANE_ID"
echo "Directory:  $CWD"
```

### 3. Build the Seed Prompt

Build the prompt as a shell variable. Reference the resolved first-pane id so
codex captures the right pane.

```bash
EXTRA="${EXTRA:-}"  # populated from the optional skill argument

ELATE_PROMPT="You are a parallel codex agent launched via the /elate skill.

Another agent (Claude Code, or a human) is working in tmux pane $FIRST_PANE_ID
of the same window. That pane is your brief.

Steps:

1. Run \`tmux capture-pane -t $FIRST_PANE_ID -p\` to read the dispatcher pane's
   visible buffer. If you need more scrollback, pass \`-S -\` to capture from
   the start of history.
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

### 4. Split, Launch Codex, Rebalance

Hand the prompt to the new pane via `-e` (an environment variable) so the new
pane's shell can pass it to codex without any quoting hazards. Split
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

### 5. Output Summary

```
Elate launched!

  Window:        <window>
  Source pane:   <first-pane-id>
  Codex pane:    vertical split (right)
  Directory:     <cwd>
```

STOP after launching. Do not interact with the new pane — codex is now driving
it independently.

## Edge Cases

### Not Inside tmux

Bail in step 1 with a hint to start tmux.

### Window Already Has Many Panes

`select-layout even-horizontal` rebalances every pane in the window, so the new
codex pane joins existing splits as an equal slice.

### Codex Not on PATH

The split still opens, but the shell command exits immediately and the pane
closes. Confirm `codex` resolves (`command -v codex`) before reporting elate
launched.
