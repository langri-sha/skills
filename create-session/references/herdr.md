# Herdr TUI procedure

Require the managed caller context validated in `SKILL.md`. Discover the
installed syntax with `herdr --help`, then `herdr workspace`, `herdr worktree`,
`herdr tab`, and `herdr pane`. Group help can exit with status 2; run each
independently. Never run bare `herdr`, which launches or attaches the TUI, or
probe a mutating nested command with missing arguments.

Use the `/herdr` skill when available for additional CLI conventions. The
commands below are supported by Herdr 0.9.3; the installed CLI is authoritative.

## Resolve the workspace

Herdr organizes Git worktrees as workspaces grouped with their source
repository. The default destination is the target worktree's workspace, which
can differ from the caller's workspace. Preserve the caller's focus.

Use `SESSION_TOPLEVEL` for the absolute Git worktree root, `SESSION_CWD` for the
invocation's actual directory, and `SESSION_SLUG` for its resolved slug. Inspect
the repository's worktrees without modifying Git, and take the repository's
source checkout from the response: the primary checkout, or `.bare` in a bare
layout.

```bash
herdr worktree list --cwd "$SESSION_TOPLEVEL" |
  jq -r '.result.source.source_checkout_path // empty'
```

Store it in `SESSION_SOURCE` and match the target by canonical path in
`.result.worktrees`. Open that existing checkout from the source; Herdr refuses
a linked worktree as `--cwd` with `linked_worktree_source`:

```bash
herdr worktree open --cwd "$SESSION_SOURCE" \
  --path "$SESSION_TOPLEVEL" --no-focus
```

`worktree open` creates or reuses the checkout's workspace and can also open its
source repository workspace to establish grouping. It does not create a new Git
worktree. Do not use `worktree create` here; `/create-worktree` handles branch
and checkout creation before this skill is invoked.

Capture `.result.workspace.workspace_id`, `.result.tab.tab_id`,
`.result.root_pane.pane_id`, and `.result.already_open` from the response. Do
not supply `--label` to `worktree open`: that can rename an existing workspace.

- When `already_open` is false, reuse the returned initial tab and root pane.
  Label the tab with the slug using
  `herdr tab rename "$SESSION_TAB" "$SESSION_SLUG"`.
- When `already_open` is true, the returned root pane can contain running work.
  Create a fresh tab in the returned workspace and use its root pane instead:

```bash
herdr tab create --workspace "$SESSION_WORKSPACE" \
  --cwd "$SESSION_CWD" --label "$SESSION_SLUG" --no-focus
```

Capture `.result.tab.tab_id` and `.result.root_pane.pane_id` from tab creation.

For an explicit `--workspace <id-or-label>`, resolve the existing workspace with
`herdr workspace get <id>` or an exact label match from `herdr workspace list`;
ask for an ID if several labels match. Create a fresh tab there with the command
above. If the destination does not exist, report it; create a new workspace only
when the user requests one. A new workspace created with
`herdr workspace create --cwd "$SESSION_CWD" --label <label> --no-focus`
supplies an initial tab and root pane to reuse.

Require successful responses and nonempty IDs before using them in another
command. IDs are opaque response values. Carry them explicitly between shell
tool calls; shell variables do not persist between calls.

## Create panes and start commands

The available root pane is the assistant's left pane. Split it to the right with
an even ratio, preserving cwd and focus:

```bash
herdr pane split --pane "$SESSION_LEFT" --direction right --ratio 0.5 \
  --cwd "$SESSION_CWD" --no-focus
```

Capture the new right pane ID from `.result.pane.pane_id`. Use
`herdr pane process-info --pane <id>` and pane reads to confirm each shell has
reached its interactive prompt, with the shell itself in the foreground, before
sending commands.

A newly opened worktree's initial shell starts at the checkout root. Prefix the
left command with a shell-quoted `cd -- <SESSION_CWD> &&` to preserve the
invocation's subdirectory as well. Quote the directory and assistant argv with a
proper quoting routine. Store the complete command in `SESSION_START_COMMAND`,
then run:

```bash
herdr pane run "$SESSION_RIGHT" 'critique --watch origin/main'
herdr pane run "$SESSION_LEFT" "$SESSION_START_COMMAND"
```

`pane run` sends command text and Enter together. It is intentional raw shell
control here; Herdr can still detect the assistant running in the pane. Never
send startup commands into the invoking agent's pane or an existing occupied
tab. Read the new panes with
`herdr pane read <id> --source recent-unwrapped --lines 40` to report immediate
startup failures. Shell panes remain available when commands exit.

## Lane requests

Lanes and `move <lane>` apply only to tmux. Herdr 0.9.3 exposes individual pane
moves, but no whole-tab transfer across workspaces; its socket API's `tab.move`
only reorders tabs within a workspace. Ask for the intended Herdr operation
before mutation. Do not substitute successive pane moves or rename workspaces to
simulate lanes.
