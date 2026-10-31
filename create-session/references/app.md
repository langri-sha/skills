# Herdr app procedure

Require the app caller validated in `SKILL.md`: `MUX=app`, with `MUX_TERMINAL`
holding the caller's hc address. The app's own manuals are `hc --skill` and
`herdr-app --skill`; the installed CLIs are authoritative. `herdr-app ls` and
`herdr-app do` need the app window to be open.

Use `SESSION_TOPLEVEL` for the absolute Git worktree root, `SESSION_CWD` for the
invocation's actual directory, `SESSION_SLUG` for its resolved slug, and
`SESSION_ARGV` for the assistant argv as an array. No shell parses the argv in
this path, so nothing is quoted.

## Resolve the space

The app groups work in spaces, each opened in a folder and holding tabs of
panes. The default destination is the space opened in the target worktree, which
can differ from the caller's space. `.folder` is the folder a space was opened
in; it does not follow a shell's later `cd`.

```bash
LS=$(herdr-app ls)
SESSION_SPACE=$(jq -r --arg f "$SESSION_TOPLEVEL" \
  '[.spaces[] | select(.folder == $f)] | if length == 1 then .[0].id else empty end' <<<"$LS")
```

For an explicit `--space <id-or-name>`, select on `.id == $q or .name == $q`
instead. Ask for an id when several spaces match, and report a destination that
matches nothing rather than creating it.

When the default finds no single space, derive an id from the worktree. Placing
a terminal under an id the app does not know creates the space with that id,
named after the folder's basename, with one tab and the terminal in it, without
moving the user's focus. The same id on a later run finds that space again, so
only a space that does not exist yet is marked new:

```bash
SESSION_NEW_SPACE=
if [ -z "$SESSION_SPACE" ]; then
  SESSION_SPACE=sp-session-$(printf '%s' "$SESSION_TOPLEVEL" | md5sum | cut -c1-12)
  jq -e --arg id "$SESSION_SPACE" 'any(.spaces[]; .id == $id)' <<<"$LS" >/dev/null || SESSION_NEW_SPACE=1
fi
```

## Start the assistant

`hc run` starts the assistant's terminal, and its `herdr.space` label places it
in a new tab of that space. The wrapper runs the argv in an interactive shell,
so the user's shell functions apply, and leaves that shell behind when the
assistant exits. `--no-parent` makes the session independent work rather than
the caller's child: it neither ends with the caller nor types notes into it.
`--keep` matches the app's own terminals, which come back as a shell in place
when their program is lost.

```bash
SESSION_LEFT=$(hc run --bg --no-parent --keep --json \
  --cwd "$SESSION_CWD" --label herdr.space="$SESSION_SPACE" -- \
  /usr/bin/bash -ic '"$@"; exec "$0" -i' /usr/bin/bash "${SESSION_ARGV[@]}" |
  jq -r '.address // empty')
: "${SESSION_LEFT:?}"
```

## Find the tab and pane

Adoption takes a moment. Wait once, bounded, then look the terminal up. The
guards stop the step before an empty id reaches a command that would otherwise
act on the focused tab or pane:

```bash
timeout 30 hc wait "$SESSION_LEFT" --timeout 3 >/dev/null
LS=$(herdr-app ls)
SESSION_TAB=$(jq -r --arg t "$SESSION_LEFT" \
  '.spaces[].tabs[] | select(any(.terminals[]; .terminal == $t)) | .id // empty' <<<"$LS")
SESSION_LEFT_PANE=$(jq -r --arg t "$SESSION_LEFT" \
  '.spaces[].tabs[].terminals[] | select(.terminal == $t) | .pane // empty' <<<"$LS")
: "${SESSION_TAB:?}" "${SESSION_LEFT_PANE:?}"
```

If a guard fails, wait once more and look again; then report the address and
stop. Never fall back to the focused pane.

## Name the tab and space

Renames do not move focus. A space created above is named after its folder, so
give it the slug as well:

```bash
herdr-app do tab.rename --id "$SESSION_TAB" --name "$SESSION_SLUG"
[ -n "$SESSION_NEW_SPACE" ] && herdr-app do space.rename --id "$SESSION_SPACE" --name "$SESSION_SLUG"
```

## Split critique

Split the assistant's pane to the right with critique as the new pane's program.
`pane.split` has no directory argument and would use the pane's current folder,
so `env -C` pins the invocation directory. The program runs bare, with no shell,
so there is nothing to wait for before it starts; the pane closes when critique
exits, and the split does not move the user's focus. It prints
`{"pane": …, "terminal": …}` on success, or `{"error": …}` and exits 1, and the
guard repeats that reply when the split fails. The `--pane` guard stops an empty
id, one not carried into this call or looked up while the app window was closed,
before a split that would otherwise land on the focused pane.

```bash
SESSION_SPLIT=$(herdr-app do pane.split --direction right \
  --pane "${SESSION_LEFT_PANE:?no pane for the assistant, or the Herdr app window is closed}" \
  --argv "$(jq -cn --arg c "$SESSION_CWD" '["env", "-C", $c, "critique", "--watch", "origin/main"]')")
SESSION_RIGHT=$(jq -r '.terminal // empty' <<<"$SESSION_SPLIT")
SESSION_RIGHT_PANE=$(jq -r '.pane // empty' <<<"$SESSION_SPLIT")
: "${SESSION_RIGHT:?split failed: $SESSION_SPLIT}" "${SESSION_RIGHT_PANE:?}"
```

## Read the start

Nothing is typed into the assistant, so read its screen for a startup failure
such as a trust dialog or an approval prompt, and show it rather than answering:

```bash
timeout 30 hc wait "$SESSION_LEFT" --timeout 10 >/dev/null
hc read "$SESSION_LEFT" --lines 40
```
