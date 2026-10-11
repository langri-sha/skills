---
name: create-session
description: >-
  Create a development session for the current worktree in tmux or Herdr,
  with an assistant and a critique watcher. Use tmux lanes or Herdr's native
  worktree workspaces; also move existing tmux windows between lanes. Use when
  asked to launch a worktree session or park or resume existing work.
metadata:
  author: langri-sha
  version: '3.0.0'
  argument-hint: '[tmux|herdr] [lane|--workspace ID] [assistant] [continue] [prompt] | tmux move <lane> [window]'
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

Inspect only the relevant environment markers:

| Candidate | Required markers | Validate before using it |
| --- | --- | --- |
| tmux | Nonempty `TMUX` and `TMUX_PANE` | `tmux display-message -p -t "$TMUX_PANE" '#{pane_id}'`; require the returned ID to equal `TMUX_PANE` |
| Herdr | `HERDR_ENV=1` and nonempty `HERDR_PANE_ID` | `herdr pane current --current`; require success and a nonempty `.result.pane.pane_id` |

An explicit backend wins. Otherwise select the sole candidate. If both
candidates exist, ask which backend to use: nested multiplexers can inherit
both environments, and precedence cannot establish the intended layer. If
neither exists, ask which backend to use before creating anything.

Never infer the runtime from installed executables, `TERM`, running servers,
or UI focus. If any marker for the selected backend exists but its required
markers are incomplete or its live lookup fails, stop and report the context
problem; do not silently switch backends or fall back to focus.

An explicit `tmux` request with no tmux markers may create a detached session
or move an explicitly named window. Herdr requires a validated managed caller
pane even when explicitly selected; do not control a focused Herdr session
from outside it. Check the selected CLI is available before mutation.

For Herdr, retain the returned live pane, tab, and workspace IDs. Inherited
`HERDR_TAB_ID` and `HERDR_WORKSPACE_ID` can be stale after pane moves; the
inherited pane ID can remain an alias, so do not require its returned ID to
match. Guard the pane marker before `--current`, which can otherwise fall back
to UI focus.

## Resolve the work and destination

For creation, use `git rev-parse --show-toplevel` to find the worktree. Its
basename is the session slug; when the basename is `main`, use the parent
directory's basename instead. Preserve the invocation's actual working
directory, including any subdirectory. Stop if creation is requested outside
a Git worktree. Moves use the existing window and do not require the caller
to be in a repository.

### tmux: session lanes

| Lane | Holds |
| --- | --- |
| `dev` | Active implementation work |
| `proposals` | Proposals and design work |
| `archive` | Parked work |

An explicit lane wins. Otherwise inherit the validated caller's tmux session
name when it exactly matches a lane; otherwise use `dev`. Reject unknown lanes
and Herdr workspace arguments. `letta` selects the assistant and
never a lane; do not put worktree sessions in the long-lived `letta` session.

Create missing lanes on demand, reusing the first window returned by session
creation. Do not leave a placeholder shell behind.

### Herdr: worktree workspaces

Default to Herdr's native workspace for the target Git worktree. Open or reuse
it with `herdr worktree open`, preserving repository/worktree grouping. Reuse
the initial tab only when the workspace is newly opened; otherwise create a
new tab so existing work is untouched. An explicit workspace destination
overrides that placement and receives a new tab in the requested directory.

Herdr has no lane argument in this skill. If a lane or `move` is requested
with Herdr, explain that it applies to tmux and ask for the intended workspace
or operation before mutation. Do not synthesize dev/proposals/archive
workspaces or translate lanes into workspace labels.

Match names and labels exactly; ask for an ID if multiple objects match.
Never derive IDs from indexes or sidebar positions.

## Build the assistant command

Default to `claude`. Construct an argv list, then shell-quote every argument
with a proper quoting routine such as Python's `shlex.join` before submitting
the command to a shell:

- Claude: `claude --name <slug> --permission-mode bypassPermissions`, plus
  `--continue` when requested and the optional prompt after `--` as one
  positional argument. Pass the prompt at startup, preserving newlines and
  literal shell characters.
- Letta: `letta --yolo`. `continue` and initial prompts in this workflow apply
  only to Claude; report unsupported options before creating panes rather
  than silently discarding them.

Do not interpolate unquoted slugs, paths, or prompts into shell command text.
Use an interactive shell pane so it survives the assistant exiting.
Before creating anything, check that the selected assistant and `critique`
are available in the launch environment.

## Run the selected procedure

Read only the reference for the resolved backend:

- [tmux](references/tmux.md): create the lane/window/panes or move a whole window.
- [Herdr](references/herdr.md): open or reuse the worktree workspace, then
  create the assistant and critique panes in an available tab.

Target all commands by captured IDs. When using separate shell tool calls,
carry the captured values explicitly; shell variables do not persist across
calls. Inspect each mutation's result before proceeding. On a partial failure,
report the created IDs and what started; do not retry by creating duplicates
or close running work automatically.

Report the backend, tmux lane or Herdr workspace, window/tab ID and label,
directory, assistant and critique pane IDs, and commands started. For a
detached tmux lane, include `tmux attach -t <lane>`. For a move, report the
source and destination lanes.

Other pane skills such as `/edit`, `/elate`, and `/lights-out` may still be
tmux-specific. This skill's backend support does not change their behavior.
