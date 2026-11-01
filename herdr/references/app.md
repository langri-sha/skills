# App facts

Facts about the Herdr app that its manuals (`hc --skill`, `herdr-app --skill`)
do not state.

## Session labels

The app keeps no record of which agent session runs in a terminal. A machine can
add one with a `SessionStart` hook that labels the terminal it runs in:

```sh
hc label "$HC_TERMINAL_ID" \
  claude.session="$session_id" claude.name="$name" \
  claude.model="$model" claude.effort="$effort" claude.cwd="$cwd"
```

The hook reads `session_id` and `cwd` from the JSON on its stdin, and writes
only the labels it knows. The verbs read these labels when present:

| Label            | Read by                  |
| ---------------- | ------------------------ |
| `claude.session` | `seat` (`session_match`) |

Without them `seat` reports `session_match: null` with a `session_reason`, and
nothing else fails.

## Placement labels

The app places a terminal started with
`hc run --label herdr.space=<id> --label herdr.tab=<id>` in that tab. It labels
every adopted terminal `where` as `<space name> / <tab name>`; `seat` falls back
to these labels when the window is closed, and `herdr-app ls` needs the window
open.
