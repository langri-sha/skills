---
name: herdr
description: >-
  Drives Herdr, the workspace for coding agents, through one script that works
  in both the Herdr app (hc and herdr-app) and the Herdr TUI (herdr): finds the
  terminal this agent runs in, identifies and reads other agents' terminals, and
  lists the roster. Use when the user mentions Herdr, the Herdr app, hc,
  herdr-app, panes, terminals or spaces, or wants to start, read, brief, restart
  or close an agent in Herdr. Not for tmux, or for starting a new worktree
  session (create-session).
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
5. **Never sleep to wait.** Use `hc wait`, `herdr agent wait` or `hc events`.

Syntax for everything the verbs do not cover is in the CLIs' own manuals, which
track the installed versions: `hc --skill`, `herdr-app --skill`, and
`herdr --help` with each group's help (`herdr agent`, `herdr pane`, ...).

## Task to verb

| Task                                            | Verb                                                   |
| ----------------------------------------------- | ------------------------------------------------------ |
| Where am I, and in which Herdr?                 | `seat`                                                 |
| Who runs in terminal T, and how do I resume it? | `whois T`                                              |
| What is on terminal T's screen?                 | `read T`, with `--tail N` or `--footer`                |
| Who is running, blocked, or missing bypass?     | `roster`, with `--label k=v` (app only)                |
| Make a space for a mission                      | `space NAME`, with `--folder`, `--tab`, `--keep-focus` |

Failures, with what to tell the user:
[references/failures.md](references/failures.md).

## Exit codes

| Code | Meaning                                                       |
| ---- | ------------------------------------------------------------- |
| 0    | Done                                                          |
| 1    | A Herdr command failed; `reason` carries its message          |
| 2    | Usage error                                                   |
| 3    | `not_found`: no such terminal, pane or agent                  |
| 4    | `no_seat`: this process is not in a Herdr app or TUI terminal |
| 5    | `space_exists`: a space of that name is open; ask the user    |
