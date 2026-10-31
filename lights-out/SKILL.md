---
name: lights-out
description: >-
  Closes the tmux window, Herdr app tab or Herdr TUI tab this agent runs in,
  after checking for unfinished work, always targeting its own pane by ID. Use
  when asked to close this window or tab, kill this window, or clean up after
  wrapping up. Not for closing other windows, tabs, sessions, spaces or
  workspaces.
metadata:
  author: langri-sha
  version: '1.2.0'
---

# lights-out

Close the tmux window, Herdr app tab or Herdr TUI tab this session lives in —
safely, and only this one.

## Why this skill exists

Bare tmux commands (`tmux kill-window` with no `-t`) resolve to the **attached
client's focused window** — whatever the user is looking at — not the window
containing this agent's pane, even when `TMUX_PANE` is set in the environment. A
bare kill once took out the wrong window while the user was focused elsewhere.
Destructive tmux commands must always carry an explicit target. Herdr TUI
commands without an explicit pane can likewise fall back to the focused one, the
Herdr app's `tab.close` and `pane.close` without an explicit id act on the
focused tab or pane, and `hc kill` without an address picks a terminal itself.

## Workflow

### 1. Pre-flight

Run these checks before killing anything. If any check fails, STOP and tell the
user — never fall back to a bare command or guess a target.

tmux sets `TMUX` and `TMUX_PANE`, the Herdr app sets `HC_TERMINAL_ID`, and the
Herdr TUI sets `HERDR_ENV` and `HERDR_PANE_ID`. When one runs inside another the
agent inherits every set. The variables only name candidates: the agent belongs
to the multiplexer whose terminal is its controlling terminal. A tool shell
often has no terminal of its own, so take the nearest ancestor's. Closing the
outer multiplexer's window or tab instead would take down every session nested
in it.

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

With `none`, this agent is not in a tmux, Herdr app or Herdr TUI pane it can
address: say so and stop. A sandbox that hides parent processes or a
multiplexer's socket also ends here; rerun the step outside it.

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

**Herdr app.** The target is the terminal the detection proved, `$MUX_TERMINAL`,
and the tab the app shows it in. Look the terminal up in `herdr-app ls`, in the
same shell call as the detection:

```bash
herdr-app ls | jq -er --arg t "${MUX_TERMINAL:?not a Herdr app terminal}" '
  .spaces[] | . as $s | .tabs[] | select(any(.terminals[]; .terminal == $t)) |
  "in: Herdr app tab \(.id) \"\(.name)\" (\(.terminals | length) terminal(s)) of space \($s.id) \"\($s.name)\" (\($s.tabs | length) tab(s))"' ||
  { echo "terminal $MUX_TERMINAL has no tab in the Herdr app"; exit 1; }
```

`$MUX_TERMINAL` is set only when the detection proved the app, so the lookup
fails closed where `$HC_TERMINAL_ID`, inherited through tmux, would name the
outer terminal. `herdr-app ls` is the app's own record of where each terminal
shows, the twin of the TUI's `tab get` and `workspace get`: it gives the tab's
terminal count and the space's tab count for the announcement. The terminal's
labels are no substitute: a terminal adopted into a tab by its `herdr.space`
label carries no `herdr.tab`. An agent whose terminal has no tab, such as a
hidden sub-agent, stops here. `herdr-app ls` and `herdr-app do` need the app
window to be open.

Like tmux's window, the whole tab closes with every terminal in it, such as a
critique pane. When the tab is the last one in its space, closing it would close
the space, so the kill step ends only this agent's own terminal instead: say so
when announcing, and that the space goes with it when this terminal is the tab's
only one.

**Herdr TUI.** The target is the live pane ID printed above, not
`HERDR_PANE_ID`: a moved pane keeps its old ID in the environment, and
`HERDR_TAB_ID` and `HERDR_WORKSPACE_ID` go stale with it. Look up where the pane
lives, in the same shell call as the detection:

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
- In the Herdr app, terminals this agent started with `hc run` end with it,
  wherever they show, unless started with `--outlive-parent`. List them in the
  same shell call as the detection, or with its address written out literally:

  ```bash
  hc ls --json | jq -r --arg t "${MUX_TERMINAL:?}" '.terminals[] | select(.parent == $t) | .address' |
    while read -r c; do hc get "$c" --json | jq -r 'select(.state == "live" and .die_with_parent) | "ends with it: \(.address) in \(.labels.where // "no tab")"'; done
  ```

  Every line is pending work, such as a worker still running in another tab.
  Never kill them yourself.

If anything is pending, report it and ask before proceeding (unless the user
already told you to close regardless).

### 3. Announce

State the window name/id, the Herdr app tab and space, or the Herdr TUI tab and
workspace being closed — or, on a space's last tab in the app, that only this
agent's own terminal ends — and name the terminals that end with it, so the user
can object if it isn't what they expect. Say goodbye **before** the kill — it
terminates this agent's process, so nothing after it will run, and no farewell
message can follow it.

### 4. Kill

As the very last tool call of the turn:

**tmux.**

```bash
tmux kill-window -t "${TMUX_PANE:?}"
```

A pane target resolves to its containing window, so this takes the whole window
— including sibling panes like a critique watcher — with it.

**Herdr app.** With more than one tab in the space, close the tab id from
pre-flight, written out literally since shell variables don't survive between
tool calls:

```bash
herdr-app do tab.close --id <tab id from pre-flight>
```

Every terminal in the tab ends with it, and the user's focus stays where it was.

On the space's last tab the app refuses with
`space.close ends its terminals: pass confirmed: true` and closes nothing. Never
pass `--confirmed true`: it ends every terminal in the tab and the space with
them. End this agent's own terminal instead:

```bash
hc kill "${HC_TERMINAL_ID:?}"
```

The app removes its pane at once. Other terminals in the tab stay, and the tab
and space with them. When this agent's terminal was the tab's only one, the app
closes the emptied tab and its space as well, before any `hc rm`, so a lone
agent ends its space just as `--confirmed true` would; what it never ends is a
sibling.

**Herdr TUI.** Close the tab ID from pre-flight, written out literally since
shell variables don't survive between tool calls:

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
- In the Herdr app, never target anything but this agent's own tab or terminal:
  no `space.close`, no `tab.close --confirmed true`, no `tab.close`,
  `pane.close`, `terminal.kill` or `hc kill` on another id or address, and no
  `window.close`, `app.quit` or `hc server stop`. Terminals this agent started
  end with it; step 2 reports them, never kills them.
- In the Herdr TUI, never close anything but this agent's own tab: no
  `workspace close`, `--group`, or `herdr server stop`.
