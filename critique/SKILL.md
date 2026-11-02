---
name: critique
description: >-
  Opens a critique watcher that reviews local changes, in a split beside this
  agent's tmux, Herdr app or Herdr TUI pane. Use when asked to start critique or
  to watch the working changes. Not for a new worktree session with its own
  watcher (create-session).
metadata:
  author: langri-
  version: '1.2.2'
---

# critique

Start a critique watcher in a split pane, in tmux, the Herdr app or the Herdr
TUI.

## Workflow

### 1. Detect the Multiplexer

Run the `herdr` skill's `seat` verb to identify this session's own terminal. Use
the path to that skill's script as `<herdr-script>`:

```bash
SEAT=$(python3 <herdr-script> seat) || { echo "$SEAT" >&2; exit 1; }
[ "$(jq -r '.session_match' <<<"$SEAT")" != false ] || { echo "Terminal belongs to another session" >&2; exit 1; }
MUX=$(jq -r '.backend' <<<"$SEAT")
PANE= MUX_TERMINAL=
case $MUX in
  tmux) PANE=$(jq -r '.target' <<<"$SEAT") ;;
  app) MUX_TERMINAL=$(jq -r '.target' <<<"$SEAT") ;;
  tui) MUX=herdr; PANE=$(jq -r '.target' <<<"$SEAT") ;;
esac
echo "multiplexer=$MUX pane=$PANE terminal=$MUX_TERMINAL"
```

A match proves the variable names this agent's own pane or terminal, so later
steps can target `$TMUX_PANE`, `$HC_TERMINAL_ID` or the Herdr TUI's `--current`,
which resolves a moved pane's inherited ID to its live one. With `none`, say
this agent is not in a tmux, Herdr app or Herdr TUI pane and stop. A sandbox
that hides parent processes or a multiplexer's socket also ends here; rerun the
step outside it.

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

**Herdr app.** Find this agent's pane from its terminal address, then split it
to the right with critique as the new pane's program:

```bash
PANE=$(herdr-app ls | jq -r --arg t "${MUX_TERMINAL:?}" \
  '.spaces[].tabs[].terminals[] | select(.terminal == $t) | .pane // empty')
herdr-app do pane.split --direction right \
  --pane "${PANE:?no pane for this terminal, or the Herdr app window is closed}" \
  --argv "$(jq -cn --arg d "$PWD" '["env", "-C", $d, "critique", "--watch", "origin/main"]')"
```

The split does not move the user's focus. It prints `{"pane": …, "terminal": …}`
on success, or `{"error": …}` and exits 1. `env -C "$PWD"` starts critique in
the worktree: `pane.split` has no directory argument and would otherwise use the
pane's current folder. The program runs directly, with no shell, so there is
nothing to wait for before it starts, and the pane closes when critique exits,
as in tmux. An agent whose terminal has no pane, such as a hidden sub-agent,
stops at the `PANE` guard; so does one whose app window is closed, since
`herdr-app ls` and `herdr-app do` need it open.

**Herdr TUI.** Split to the right without moving the user's focus, wait for the
new shell to draw its prompt so the command isn't typed into a shell still
starting up, then run critique in it. `herdr pane --help` has the installed
syntax.

```bash
CRITIQUE_PANE=$(herdr pane split --pane "${PANE:?}" --direction right --cwd "$PWD" --no-focus |
  jq -r '.result.pane.pane_id // empty')
: "${CRITIQUE_PANE:?split failed}"
herdr pane wait-output "$CRITIQUE_PANE" --source visible --regex '\S' --timeout 10000 >/dev/null
herdr pane run "$CRITIQUE_PANE" 'critique --watch origin/main'
```

The pane keeps its shell after critique exits.

Report the directory and, in the Herdr app, the new terminal's address, or in
the Herdr TUI, the new pane's ID.
