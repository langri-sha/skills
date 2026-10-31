---
name: create-session
description: >-
  Opens a development session for the current worktree, an assistant beside a
  critique watcher, in a tmux lane or the worktree's Herdr workspace, and moves
  tmux windows between lanes. Use when asked to launch a session for a worktree,
  or to park or resume work. Not for creating the worktree (create-worktree).
argument-hint:
  '[tmux|herdr] [lane|--workspace ID] [assistant] [continue] [prompt] | tmux
  move <lane> [window]'
metadata:
  author: langri-sha
  version: '3.1.0'
---

# Create session

Create an assistant pane on the left and `critique --watch origin/main` on the
right, both in the invocation's working directory. Keep the caller's focus.
Arguments are recognized by value: backend (`tmux`, `herdr`), tmux lane (`dev`,
`proposals`, `archive`), assistant (`claude`, `letta`), `continue`, and an
optional initial prompt. Herdr accepts an optional `--workspace <id-or-label>`
destination. `tmux move <lane> [window]` operates on existing windows; its
destination lane is required.

Examples: `/create-session`, `/create-session herdr --workspace wM`,
`/create-session tmux claude continue`, `/create-session tmux move archive @12`.

## Resolve the backend

tmux sets `TMUX` and `TMUX_PANE`, the Herdr app sets `HC_TERMINAL_ID`, and the
Herdr TUI sets `HERDR_ENV` and `HERDR_PANE_ID`. When one runs inside another the
caller inherits every set. The variables only name candidates: the caller
belongs to the multiplexer whose terminal is its controlling terminal. A tool
shell often has no terminal of its own, so take the nearest ancestor's:

```bash
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
```

A match proves the variable names the caller's own pane or terminal. Without an
explicit backend, use the detected one. With `none`, say the caller is not in a
tmux, Herdr app or Herdr TUI pane and stop; an explicit `tmux` can still create
a detached lane. A sandbox that hides parent processes or a multiplexer's socket
also ends in `none`; rerun the step outside it.

Never infer the runtime from installed executables, `TERM`, running servers, or
UI focus, and never fall back to focus when detection fails.

An explicit `tmux` request outside a tmux caller may create a detached session
or move an explicitly named window. The Herdr app and the Herdr TUI each require
a caller of their own even when explicitly selected: when detection finds
another multiplexer or none, an inherited `HC_TERMINAL_ID` or the TUI markers
belong to an outer terminal, so report that and stop rather than control either
from outside it. Check the selected CLI is available before mutation.

For the Herdr TUI, take the live tab and workspace IDs from
`herdr pane current --current`. Inherited `HERDR_TAB_ID` and
`HERDR_WORKSPACE_ID` go stale after pane moves, while the inherited pane ID
stays an alias that `--current` resolves.

In the Herdr app, `MUX_TERMINAL` is an hc address, not a pane. Never run a
`herdr …` command from the app: it belongs to the TUI, and acts on the user's
focused TUI pane.

## Resolve the work and destination

For creation, use `git rev-parse --show-toplevel` to find the worktree. Its
basename is the session slug; when the basename is `main`, use the parent
directory's basename instead. Preserve the invocation's actual working
directory, including any subdirectory. Stop if creation is requested outside a
Git worktree. Moves use the existing window and do not require the caller to be
in a repository.

### tmux: session lanes

| Lane        | Holds                      |
| ----------- | -------------------------- |
| `dev`       | Active implementation work |
| `proposals` | Proposals and design work  |
| `archive`   | Parked work                |

An explicit lane wins. Otherwise, when the caller is in tmux, inherit its tmux
session name if it exactly matches a lane; otherwise use `dev`. Reject unknown
lanes and Herdr workspace arguments. `letta` selects the assistant and never a
lane; do not put worktree sessions in the long-lived `letta` session.

Create missing lanes on demand, reusing the first window returned by session
creation. Do not leave a placeholder shell behind.

### Herdr: worktree workspaces

Default to Herdr's native workspace for the target Git worktree. Open or reuse
it with `herdr worktree open`, preserving repository/worktree grouping. Reuse
the initial tab only when the workspace is newly opened; otherwise create a new
tab so existing work is untouched. An explicit workspace destination overrides
that placement and receives a new tab in the requested directory.

Herdr has no lane argument in this skill. If a lane or `move` is requested with
Herdr, explain that it applies to tmux and ask for the intended workspace or
operation before mutation. Do not synthesize dev/proposals/archive workspaces or
translate lanes into workspace labels.

Match names and labels exactly; ask for an ID if multiple objects match. Never
derive IDs from indexes or sidebar positions.

## Build the assistant command

Default to `claude`. Construct an argv list, then shell-quote every argument
with a proper quoting routine such as Python's `shlex.join` before submitting
the command to a shell:

- Claude: `claude --name <slug> --permission-mode bypassPermissions`, plus
  `--continue` when requested and the optional prompt after `--` as one
  positional argument. Pass the prompt at startup, preserving newlines and
  literal shell characters.
- Letta: `letta --yolo`. `continue` and initial prompts in this workflow apply
  only to Claude; report unsupported options before creating panes rather than
  silently discarding them.

Do not interpolate unquoted slugs, paths, or prompts into shell command text.
Use an interactive shell pane so it survives the assistant exiting. Before
creating anything, check that the selected assistant and `critique` are
available in the launch environment.

## Run the selected procedure

Read only the reference for the resolved backend:

- [tmux](references/tmux.md): create the lane/window/panes or move a whole
  window.
- [Herdr](references/herdr.md): open or reuse the worktree workspace, then
  create the assistant and critique panes in an available tab.

Target all commands by captured IDs. When using separate shell tool calls, carry
the captured values explicitly; shell variables do not persist across calls.
Inspect each mutation's result before proceeding. On a partial failure, report
the created IDs and what started; do not retry by creating duplicates or close
running work automatically.

Report the backend, tmux lane or Herdr workspace, window/tab ID and label,
directory, assistant and critique pane IDs, and commands started. For a detached
tmux lane, include `tmux attach -t <lane>`. For a move, report the source and
destination lanes.
