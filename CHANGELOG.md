# skills

## 1.1.0

### Minor Changes

- e6d33a6: Start elate's codex agent in the Herdr app as well as tmux and the Herdr TUI.
- 47a6729: Let elate start Claude Code or codex with a chosen model and effort, defaulting
  to codex on `gpt-6.1-sol` at `xhigh`. In tmux the launch now goes through the
  user's shell functions, as in the app, so a wrapper such as `op run` runs for
  each pane, and the pane keeps a shell after the agent exits.
- 39cf61c: Open the critique pane in the Herdr app as well as tmux and the Herdr TUI.
- a99f03d: The worktree reaper treats a worktree as in use when a Herdr app terminal was
  launched inside it, or a Herdr app tab or space carries its name.
- 23de5df: Open the default nvim split in the Herdr app as well as tmux and the Herdr TUI.
- 2a0a804: Close the agent's own Herdr app tab in lights-out, as well as its tmux window or Herdr TUI tab.
- 89074f0: Open subdivide's session in the Herdr app as well as tmux and the Herdr TUI.
- d2bdb98: Open create-session's session in the Herdr app as well as tmux and the Herdr
  TUI: a new tab in the space opened in the worktree, or a new space named after
  the worktree when none is.

### Patch Changes

- 6ef8c7d: Keep critique's multiplexer detection from overwriting `TERMINAL`, which desktop
  sessions export for `xdg-terminal-exec`.
- 6ccccec: Run subdivide's create-session commands from the new worktree, so the session
  opens for it rather than for the caller's worktree.
- a73996e: The worktree reaper checks that an hc core is listening before calling `hc`, so
  a dry run no longer starts a core when none is running or a stale socket file is
  left behind, and it reports any other `hc` failure or an unreadable reply as
  `hc UNAVAILABLE` instead of zero terminals.
- 921675b: Print `pane.split`'s reply in create-session's Herdr app path, so a failed
  critique split shows the app's error.
- 4db0f13: Print `pane.split`'s reply when the split fails in edit's Herdr app path, so the
  app's error reaches the agent.
- da8f37d: Print `pane.split`'s reply in critique's Herdr app path, so the new terminal's
  address and any error reach the agent.
- 42a9abb: Match elate's Claude model names regardless of case, so `Opus` starts claude as
  `opus` does, and drop the `opusplan` pattern that `opus*` already covered.

## 1.0.0

### Major Changes

- cf1f5fe: The first tagged release, so consumers can pin a version instead of a commit.
