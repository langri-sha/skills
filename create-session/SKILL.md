---
name: create-session
description: >-
  Create a tmux dev window for the current worktree in a session lane, or move
  an existing window between lanes. Resolves the worktree slug and the target
  lane (dev, proposals, or archive), creates the lane session on demand, and
  opens a window named after the slug with an AI assistant (claude or letta) on
  the left pane and `critique --watch origin/main` on the right. Also parks
  work: "move this window to archive", "put this in proposals", "pull it back
  into dev". Accepts optional arguments for the lane and the assistant
  (defaults: the current window's lane or dev; claude).
metadata:
  author: langri-sha
  version: '2.0.0'
  argument-hint: '[lane] [assistant] [continue] [prompt] | move <lane> [window]'
---

# create-session

Create a tmux development window for the current worktree, in the right session
lane — or move an existing window between lanes.

## Session Lanes

Windows are grouped into named tmux sessions — lanes — by the kind of work they
hold:

| Lane        | Holds                                                        | Default |
| ----------- | ------------------------------------------------------------ | ------- |
| `dev`       | Active implementation work — the day-to-day worktree windows | yes     |
| `proposals` | Ongoing work on proposals and design docs                    | no      |
| `archive`   | Work put on break — parked, not abandoned                    | no      |

Lanes are created on demand, so a fresh machine needs no setup. tmux destroys a
session whose last window leaves; a lane vanishing when emptied is the same
lifecycle in reverse and nothing to fix.

The `letta` session is **outside** the lane system: it hosts long-lived agent
windows (`ops`, `scratch`, `docs`, ...), not worktree windows. Never
create worktree windows in it, and never resolve a lane to it — `letta` as an
argument selects the assistant, not a session.

Pane-relative skills (`/critique`, `/edit`, `/elate`, `/lights-out`) target
their own pane via `$TMUX_PANE` and keep working unchanged in whatever lane
their window lives in.

## Arguments

Arguments are recognized by value, not position — the lane and assistant
vocabularies are disjoint.

| Argument    | Default  | Description                                                   |
| ----------- | -------- | ------------------------------------------------------------- |
| `lane`      | resolved | Target lane: `dev`, `proposals`, or `archive` (see step 2)    |
| `assistant` | `claude` | AI assistant to launch: `claude` or `letta`                   |
| `continue`  | no       | If specified, pass `--continue` to claude                     |
| `prompt`    | empty    | Optional initial prompt to pass directly to Claude at startup |
| `move`      | —        | `move <lane> [window]` — move a window instead (see below)    |

Default to `claude` without asking if the user doesn't specify an assistant. The
`continue` option only applies to `claude`. When an initial Claude prompt is
available, pass it on the Claude command line instead of starting Claude first
and sending the prompt afterward via tmux.

## Workflow

### 1. Resolve Worktree

Detect the current worktree slug from the worktree's top-level directory. In the
bare-repo layout (see `/create-worktree`), every branch is a worktree directory
whose basename is the slug — this also covers nested layouts like Letta's
`main/.letta/worktrees/<slug>`:

```bash
TOPLEVEL=$(git rev-parse --show-toplevel)
SLUG=$(basename "$TOPLEVEL")
CWD=$(pwd)

# The main worktree's basename is just "main" — use the repo name instead
# so windows stay distinguishable across repos.
if [ "$SLUG" = "main" ]; then
  SLUG=$(basename "$(dirname "$TOPLEVEL")")
fi

echo "Worktree slug: $SLUG"
echo "Working directory: $CWD"
```

### 2. Resolve Session Lane

Resolution order: an explicit lane argument wins; otherwise inherit the lane of
the window this skill was invoked from; otherwise `dev`.

```bash
LANES="dev proposals archive"
LANE="${LANE:-}" # explicit lane argument, when given

# Reject anything that isn't a lane — letta especially.
if [ -n "$LANE" ]; then
  case " $LANES " in
    *" $LANE "*) ;;
    *)
      echo "Error: unknown lane '$LANE' (valid: $LANES)"
      exit 1
      ;;
  esac
fi

# Inherit the current window's lane when invoked from inside one. Target the
# pane explicitly: a bare display-message follows the attached client's
# focused window, not this pane.
if [ -z "$LANE" ] && [ -n "${TMUX_PANE:-}" ]; then
  CURRENT=$(tmux display-message -p -t "$TMUX_PANE" '#{session_name}' 2>/dev/null)
  case " $LANES " in
    *" $CURRENT "*) LANE="$CURRENT" ;;
  esac
fi

# Non-lane sessions (letta, anything else) fall through to the default.
LANE="${LANE:-dev}"

# One-time migration: the pre-lane layout kept dev work in a session named 0.
# Rename it (windows are undisturbed) rather than growing an empty dev lane
# beside it.
if [ "$LANE" = dev ] && ! tmux has-session -t '=dev' 2>/dev/null &&
  tmux has-session -t '=0' 2>/dev/null; then
  tmux rename-session -t '=0' dev
  echo "Migrated legacy session '0' -> 'dev'"
fi

echo "Lane: $LANE"
```

The `=` prefix pins session lookups to an exact name. Without it tmux
prefix-matches, and a session like `devops` would pass for `dev`.

### 3. Determine Assistant Command

Based on the chosen assistant:

| Assistant | Command                                                                                 |
| --------- | --------------------------------------------------------------------------------------- |
| `claude`  | `claude --name <slug> --permission-mode bypassPermissions [--continue] [< prompt-file]` |
| `letta`   | `letta --yolo`                                                                          |

```bash
ASSISTANT="${ASSISTANT:-claude}"
CONTINUE="${CONTINUE:-no}"  # "yes" if user said continue
PROMPT="${PROMPT:-}"

case "$ASSISTANT" in
  claude)
    ASSISTANT_CMD="claude --name $SLUG --permission-mode bypassPermissions"
    if [ "$CONTINUE" = "yes" ]; then
      ASSISTANT_CMD="$ASSISTANT_CMD --continue"
    fi
    if [ -n "$PROMPT" ]; then
      PROMPT_FILE="/tmp/prompt-$(date -u +%Y%m%dT%H%M%SZ).md"
      printf '%s\n' "$PROMPT" > "$PROMPT_FILE"
      ASSISTANT_CMD="$ASSISTANT_CMD < $PROMPT_FILE"
    fi
    ;;
  letta)
    ASSISTANT_CMD="letta --yolo"
    ;;
  *)
    echo "Error: Unknown assistant '$ASSISTANT'. Use 'claude' or 'letta'."
    exit 1
    ;;
esac
```

### 4. Create Window and Panes

Create the window in the resolved lane, then split it vertically; the right pane
runs `critique --watch origin/main` from the same working directory. When the
lane session doesn't exist yet, create it with this window as its first window —
no stray shell window is left behind, and `new-session -d` also starts the tmux
server when none is running.

```bash
# Capture the window id (@N): ids are stable, window indexes renumber.
if tmux has-session -t "=$LANE" 2>/dev/null; then
  # Empty window component (lane:) appends at the next unused index.
  WINDOW_TARGET=$(tmux new-window -t "=$LANE:" -n "$SLUG" -c "$CWD" -P -F '#{window_id}')
else
  WINDOW_TARGET=$(tmux new-session -d -s "$LANE" -n "$SLUG" -c "$CWD" -P -F '#{window_id}')
fi

# Start assistant via send-keys (pane survives if assistant exits)
tmux send-keys -t "$WINDOW_TARGET" "$ASSISTANT_CMD" Enter

# Split right pane for critique
tmux split-window -t "$WINDOW_TARGET" -h -c "$CWD" "critique --watch origin/main"

# Balance the panes evenly
tmux select-layout -t "$WINDOW_TARGET" even-horizontal
```

### 5. Output Summary

After creating, display:

```
Dev window created!

  Lane:       <lane>
  Window:     <slug>
  Directory:  <cwd>

  Left pane:  <assistant command>
  Right pane: critique --watch origin/main
```

## Moving a Window Between Lanes

`move <lane> [window]` re-parents a window instead of creating one —
`move archive` parks the current work on break, `move dev <slug>` pulls it back.
The panes and whatever runs in them are untouched; the window only changes
session. The destination lane is required and validated as in step 2 — refuse
`letta`.

### 1. Resolve the Window

With no window argument, move the window this skill was invoked from. With a
window name, match it exactly across all sessions — tmux `-t` prefix-matches
names, and window names are worktree slugs that share long prefixes.

```bash
if [ -n "${WINDOW_NAME:-}" ]; then
  WINDOW_ID=$(tmux list-windows -a -F '#{window_id} #{window_name}' |
    awk -v s="$WINDOW_NAME" 'substr($0, index($0, " ") + 1) == s {print $1}')
else
  : "${TMUX_PANE:?not inside tmux — name the window to move}"
  WINDOW_ID=$(tmux display-message -p -t "$TMUX_PANE" '#{window_id}')
fi

# Fail closed: an empty -s target silently falls back to a default window,
# and tmux would move some unrelated window (even one of letta's).
if [ -z "$WINDOW_ID" ]; then
  echo "Error: no window named '$WINDOW_NAME'"
  exit 1
fi
```

More than one match (the same slug parked in two lanes): list the candidates
with `tmux list-windows -a -F '#{window_id} #{session_name}:#{window_name}'` and
ask which one.

### 2. Move It

```bash
SRC=$(tmux display-message -p -t "$WINDOW_ID" '#{session_name}')
if [ "$SRC" = "$LANE" ]; then
  echo "Window already in '$LANE'"
  exit 0
fi

# Create the destination lane on demand. Its placeholder window is killed
# after the move — by captured id, never a bare kill-window.
PLACEHOLDER=""
if ! tmux has-session -t "=$LANE" 2>/dev/null; then
  PLACEHOLDER=$(tmux new-session -d -s "$LANE" -P -F '#{window_id}')
fi

# Trailing colon: append at the next unused index. Without it tmux tries to
# overwrite a window at the destination.
tmux move-window -s "$WINDOW_ID" -t "=$LANE:"

if [ -n "$PLACEHOLDER" ]; then
  tmux kill-window -t "$PLACEHOLDER"
fi
```

Moving the window you're invoked from is safe: everything in it keeps running;
the window just leaves this session's window list. When the last window leaves a
lane, tmux destroys the emptied session — it comes back on demand.

### 3. Output

```
Window moved!

  Window: <name>
  From:   <source session>
  To:     <lane>
```

## Edge Cases

### No tmux Server Running

Not an error anymore: `new-session -d` starts the server and the lane together.
The window comes up detached — tell the user to `tmux attach -t <lane>`.

### Legacy Session `0`

Handled in step 2: when `dev` is missing but a session named `0` exists, the
skill renames `0` to `dev` instead of creating an empty lane beside it. The
windows and their indexes are undisturbed.

### Already Inside tmux

If `$TMUX` is set, the commands still work — tmux CLI operates on the server
regardless. The current window's lane becomes the default target (step 2).

### Main Repo (Not a Worktree)

Falls back to using the repository name as the window name.
