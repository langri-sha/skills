# Pane procedures

Resolve the installed `herdr` skill directory separately from this skill.
Commands below use `SOURCE`, `DESTINATION` and paths as placeholders: substitute
verified literal values, shell-quoted with a routine such as Python's
`shlex.join`. Shell variables do not persist between tool calls.

## Herdr app

Read `hc --skill`, `herdr-app --skill` and `herdr-app commands`. Resolve
SOURCE's pane from `herdr-app ls`, not from its terminal address or a sidebar
index.

Create an empty split explicitly to its right:

```sh
herdr-app do pane.split --direction right --pane SOURCE_PANE
```

Record the returned terminal and pane IDs. Verify with
`hc get DESTINATION --json` that the destination is independent of SOURCE: no
parent link to SOURCE and no lifetime dependency on it. If that is not true,
stop before launching and use the installed CLI's documented
independent-terminal placement; never close SOURCE while this dependency
remains.

Use the herdr skill's `launch --in DESTINATION --agent codex --cwd CWD` (or
`claude`), with model/effort only when selected, and the appropriate explicit
permission flag. Inspect `launch --help` and its permission behavior first: its
defaults may enable bypass. Preserve stricter source/user constraints with the
CLI's supported flags; if the helper cannot express them, launch through an
interactive shell with the native agent's flags instead. Codex in the app needs
`--no-daemon` so its commands remain in its terminal. Claude's authorized bypass
mode is `--permission-mode bypassPermissions`; Codex's is `--yolo`. Neither is
implied just by choosing a target harness.

The launch must run through the user's interactive shell functions, one agent at
a time. Report a password-manager approval or launcher error and retain both
panes. Once ready, use `deliver DESTINATION --file SEED_PATH` and inspect its
result before retrying. Use `whois DESTINATION` and `hc get DESTINATION --json`
to check the real agent/session and recovery labels. Keep source provenance in
the handoff, not the successor's `claude.session` or `codex.session` label.

Before closing, enumerate SOURCE's live descendants using `hc ls --json` and
`hc get`; account for every descendant that dies with its parent, not merely the
new successor. Revalidate the source seat and use its captured address:

```sh
hc kill SOURCE_TERMINAL
```

Do not close the tab, space, or app. Do not use the herdr skill's `close` verb
on yourself: it is for children owned by its caller.

## tmux

The tty-verified seat gives SOURCE as a stable `%N` pane ID. Verify `$TMUX`
identifies the same server and `tmux list-panes -t SOURCE` still finds it.

```sh
tmux split-window -h -d -t SOURCE -c CWD -P -F '#{pane_id}'
```

This creates an idle shell immediately to SOURCE's right without rearranging
other panes or changing focus. Record the returned ID. Launch the target through
that interactive shell using a properly quoted command, passing explicit
permission flags appropriate to the user's existing constraints. Use
`tmux send-keys -t DESTINATION -l -- QUOTED_COMMAND`, then a separately targeted
Enter. Supply the seed as one quoted startup argument or point to its file. Do
not infer launch success from `split-window` succeeding. Check the actual
process and acknowledgement file; shell prompts and dialogs do not qualify.

Read this source's scrollback, never the window's first pane. Before shutdown,
verify SOURCE and DESTINATION are distinct live panes on the same server and
that jobs tied to SOURCE's tty have been checkpointed or moved. Then:

```sh
tmux kill-pane -t SOURCE
```

Never `kill-window`, `kill-session`, or an untargeted command.

## Herdr TUI

Use the tty-verified live pane ID, not inherited tab/workspace IDs. Read the
installed `herdr pane split --help`, `herdr pane close --help`, and the herdr
skill before mutation.

```sh
herdr pane split --pane SOURCE --direction right --cwd CWD --no-focus
```

Record `.result.pane.pane_id`. Launch through the herdr skill's
`launch --in DESTINATION`, preserving the same permission and shell-wrapper
constraints as the app procedure. Send the seed through `deliver --file`. Check
live agent/session state and acknowledgement, and account for workers and jobs
that depend on the source before transferring ownership. Then:

```sh
herdr pane close SOURCE
```

Never close the tab or workspace. If the installed CLI does not support a
pane-only close, retain SOURCE and report that limitation.
