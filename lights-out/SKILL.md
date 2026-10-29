---
name: lights-out
description: >-
  Safely close the tmux window or Herdr tab this agent session lives in — last
  one out turns off the lights. Use when the user says "/lights-out", "kill this
  window", "close this window", "close this tab", or wants the agent to clean up
  its own tmux window or Herdr tab after wrapping up. Always targets the agent's
  own pane explicitly; never runs bare tmux kill commands.
metadata:
  author: langri-sha
  version: '1.1.0'
---

# lights-out

Close the tmux window or Herdr tab this session lives in — safely, and only this
one.

## Why this skill exists

Bare tmux commands (`tmux kill-window` with no `-t`) resolve to the **attached
client's focused window** — whatever the user is looking at — not the window
containing this agent's pane, even when `TMUX_PANE` is set in the environment. A
bare kill once took out the wrong window while the user was focused elsewhere.
Destructive tmux commands must always carry an explicit target. Herdr commands
without an explicit pane can likewise fall back to the focused one.

## Workflow

### 1. Pre-flight

Run these checks before killing anything. If any check fails, STOP and tell the
user — never fall back to a bare command or guess a target.

Herdr sets `HERDR_ENV` and `HERDR_PANE_ID`, tmux sets `TMUX` and `TMUX_PANE`,
and when one runs inside the other the agent inherits both sets. The variables
only name candidates: the agent belongs to the multiplexer whose pane terminal
is its controlling terminal. A tool shell often has no terminal of its own, so
take the nearest ancestor's. Closing the outer multiplexer's window or tab
instead would take down every session nested in it.

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
```

With `none`, this agent is not in a tmux or Herdr pane it can address: say so
and stop. A sandbox that hides parent processes or the multiplexer's socket also
ends here; rerun the step outside it.

**tmux.** Resolve the target window from this session's own pane:

```bash
: "${TMUX:?not inside tmux}" "${TMUX_PANE:?no pane id}"
tmux list-panes -t "$TMUX_PANE" >/dev/null || { echo "pane $TMUX_PANE is gone"; exit 1; }
tmux display-message -p -t "$TMUX_PANE" 'closing: #S:#I #W (#{window_id})'
```

Each guard covers a distinct failure that would otherwise be silent:

- `${TMUX_PANE:?}` — an empty target (`-t ""`) resolves to the user's focused
  window, the exact bug this skill exists to prevent.
- `${TMUX:?}` — without `$TMUX` the client falls back to the default socket,
  where the same `%N` can name an unrelated pane on the wrong server.
- `list-panes` — `display-message` exits 0 with empty output for a vanished
  pane, so it cannot serve as the existence check; `list-panes` genuinely fails.

Never substitute a window index (`-t 0:10`) — indexes renumber; only the pane id
(`%N`) and window id (`@N`) are stable.

**Herdr.** The target is the live pane ID printed above, not `HERDR_PANE_ID`: a
moved pane keeps its old ID in the environment, and `HERDR_TAB_ID` and
`HERDR_WORKSPACE_ID` go stale with it. Look up where the pane lives, in the same
shell call as the detection:

```bash
read -r TAB WS < <(herdr pane get "$PANE" | jq -r '.result.pane // empty | "\(.tab_id) \(.workspace_id)"')
: "${TAB:?pane $PANE is gone}" "${WS:?}"
herdr tab get "$TAB" | jq -r \
  '.result.tab | "closing: Herdr tab \(.tab_id) \(.label) (\(.pane_count) pane(s))"'
herdr workspace get "$WS" | jq -r \
  '.result.workspace | "in workspace \(.workspace_id) \(.label): \(.tab_count) tab(s)"'
```

Like tmux's window, the whole tab closes with every pane in it, such as a
critique watcher. Closing a workspace's last tab closes the workspace too, so
say so when announcing.

### 2. Check for Unfinished Business

- `git status --porcelain` — uncommitted changes?
- `git rev-parse --abbrev-ref '@{u}'` — no upstream means the branch was never
  pushed: treat that as pending, then `git log '@{u}..' --oneline` for unpushed
  commits when an upstream exists.
- Running background tasks, monitors, or workflows in this session?

If anything is pending, report it and ask before proceeding (unless the user
already told you to close regardless).

### 3. Announce

State the window name/id or the Herdr tab and workspace being closed, so the
user can object if it isn't what they expect. Say goodbye **before** the kill —
it terminates this agent's process, so nothing after it will run, and no
farewell message can follow it.

### 4. Kill

As the very last tool call of the turn:

**tmux.**

```bash
tmux kill-window -t "${TMUX_PANE:?}"
```

A pane target resolves to its containing window, so this takes the whole window
— including sibling panes like a critique watcher — with it.

**Herdr.** Close the tab ID from pre-flight, written out literally since shell
variables don't survive between tool calls:

```bash
herdr tab close <tab id from pre-flight>
```

If this is the last tab in a workspace that heads a worktree group, Herdr
refuses with `confirmation_required`, because closing it would close the group's
linked workspaces too. The agent is still running then: report it and leave the
tab open.

## Never

- Never `kill-session` or `kill-server` — the blast radius is every other window
  the user has open.
- In Herdr, never close anything but this agent's own tab: no `workspace close`,
  `--group`, or `herdr server stop`.
