---
name: herdr
description: >-
  Drives Herdr, the workspace for coding agents, through one script that works
  in both the Herdr app (hc and herdr-app) and the Herdr TUI (herdr): finds the
  terminal this agent runs in, identifies and reads other agents' terminals,
  lists the roster, makes spaces, launches, briefs, relaunches and moves agents.
  Use when the user mentions Herdr, the Herdr app, hc, herdr-app, panes,
  terminals or spaces, or wants to start, read, brief, restart or close an agent
  in Herdr. Not for tmux, or for starting a new worktree session
  (create-session).
metadata:
  author: langri-sha
  version: '1.0.0'
---

# Herdr

Two Herdrs can run side by side: the app (`herdr-app` with `hc`; spaces, tabs
and terminals addressed `t7`) and the TUI (`herdr`; workspaces, tabs and panes
addressed `w1:p2`). `scripts/herdr.py` hides the difference. Every verb prints
one JSON line, `{ok, verb, ...}`, and exits with a code from the table below.

```
python3 <skill-dir>/scripts/herdr.py <verb> [options]
```

## Contract

1. **Run `seat` first.** It walks up from this process to the controlling tty
   and reports which tmux pane, app terminal or TUI pane owns it. Environment
   variables (`HC_TERMINAL_ID`, `HERDR_*`, `TMUX_PANE`) only nominate
   candidates, because nested sessions and background jobs inherit them; the tty
   decides. Pass its `target` to the other verbs. If `backend` is `tmux`, or
   `seat` exits 4 (`no_seat`), this is not a Herdr seat: say so and stop.
2. **`session_match: false`** means the terminal belongs to another session: a
   background job holding an inherited address, or a continued session. Ask
   which terminal is the user's before placing anything beside it.
   `session_match: null` means the machine records no session for terminals;
   `session_reason` says why. See [references/app.md](references/app.md).
3. **From the app, never run `herdr` with `--current` or without a target.** The
   TUI CLI still works there and acts on whichever TUI pane the user focuses.
4. **Never guess state from screen text.** `status` and `dialog` come from the
   verbs; a `blocked` terminal needs the user, so show its dialog and ask.
   `dialog --answer` acts only on the folder-trust dialog and exits 9 on any
   other; never answer a permission dialog yourself.
5. **Never sleep to wait.** Use `hc wait`, `herdr agent wait` or `hc events`.
6. **Launch through `launch`, one agent at a time.** It types into an
   interactive shell so the user's shell functions run; `hc run claude` or the
   binary itself would skip them. A function may ask the user to approve each
   launch (a password manager, say), and a burst times out: tell the user before
   each launch, and on a launcher failure stop and report it. It never retries.
7. **Pass the permission flag on every launch.** Nothing inherits it, and the
   settings default is stricter. `launch` adds it and checks the footer.
8. **A shell is idle by its process tree**, never by `status` alone, which goes
   stale. `launch` refuses a shell that runs a program.
9. **Exit an agent with `relaunch`**, which presses ctrl+c twice. `/exit` sent
   as text arrives tagged and may never run, and a raw `kill` of the shell skips
   the checks that keep the terminal at its address.
10. **Clean up only terminals you started.** `close` refuses any terminal whose
    parent is not the caller, and `launch` makes the caller the parent.

Syntax for everything the verbs do not cover is in the CLIs' own manuals, which
track the installed versions: `hc --skill`, `herdr-app --skill`, and
`herdr --help` with each group's help (`herdr agent`, `herdr pane`, ...).

`launch` accepts repeated `--arg=VALUE` options and `--prompt-file PATH` for
agent options and a startup prompt. The file is read verbatim as one argument;
when the prompt starts work immediately, a working status counts as a successful
start. A blocked or failed launch is reported without resending the prompt.

## Task to verb

| Task                                                                                                                                 | Verb                                                                        |
| ------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| Where am I, and in which Herdr?                                                                                                      | `seat`                                                                      |
| Who runs in terminal T, and how do I resume it?                                                                                      | `whois T`                                                                   |
| What is on terminal T's screen?                                                                                                      | `read T`, with `--tail N` or `--footer`                                     |
| Who is running, blocked, or missing bypass?                                                                                          | `roster`, with `--label k=v` (app only)                                     |
| Make a space for a mission                                                                                                           | `space NAME`, with `--folder`, `--tab`, `--keep-focus`                      |
| Start an agent in an idle shell                                                                                                      | `launch --in T --agent claude --model M`                                    |
| Start an agent in a new terminal, placed by space and tab; it is the caller's child unless `--no-parent`                             | `launch --space S --tab T --name N` or `--worker-of T` (app only)           |
| Brief an agent                                                                                                                       | `deliver T "text"` or `deliver T --file path`                               |
| What dialog is a blocked terminal showing, and can the folder-trust dialog be answered?                                              | `dialog T`, with `--answer OPTION` for the folder-trust dialog only         |
| Swap, resume or restart the agent in a terminal; every failure says whether the agent exited (`exited_agent`) and carries `previous` | `relaunch T`, with `--resume`, `--agent`, `--model`, `--handoff PATH`       |
| Finish with a worker you started                                                                                                     | `close T`, with `--brief PATH` to file its brief under `closed/` (app only) |
| Follow the status of a group of terminals                                                                                            | `watch --label k=v`, then run the printed command as a monitor (app only)   |
| Move a placed terminal to another space and tab                                                                                      | `move T --space S --tab T`                                                  |

Failures, with what to tell the user:
[references/failures.md](references/failures.md).

## Exit codes

| Code | Meaning                                                                                                                                   |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 0    | Done                                                                                                                                      |
| 1    | A Herdr command failed; `reason` carries its message                                                                                      |
| 2    | Usage error                                                                                                                               |
| 3    | `not_found`: no such terminal, pane or agent                                                                                              |
| 4    | `no_seat`: this process is not in a Herdr app or TUI terminal                                                                             |
| 5    | `space_exists`: a space of that name is open; ask the user                                                                                |
| 6    | `launcher_failed`: the launch line failed, or the shell prompt came back                                                                  |
| 7    | `timeout`: not ready in time; `status` and `footer` show where it stopped                                                                 |
| 8    | The terminal is not in the state the verb needs, such as a shell running a program                                                        |
| 9    | `blocked`: a dialog is open; `dialog` has its `kind`, `msg` and `options`. Ask the user                                                   |
| 10   | `unconfirmed`: sent, but the agent did not start working; it may have arrived, so read before sending again                               |
| 11   | `finished`: the terminal ended                                                                                                            |
| 12   | `not_owned`: the terminal's parent is not the caller, so it is not yours to close                                                         |
| 13   | `held_focus` or `held_input`: the terminal has the user's focus, or text is typed at its prompt, so its shell is left alone. Ask the user |
