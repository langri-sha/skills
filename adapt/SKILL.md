---
name: adapt
description: >-
  Transfers this session to another agent in a new pane to its right, with a
  handoff before closing the source pane. Use when asked to adapt or migrate the
  current conversation to Claude Code or Codex. Not for parallel work (elate),
  new worktree sessions (create-session), or resuming in place (herdr).
argument-hint: 'claude|codex [model] [effort] [--dry-run|--rehearse]'
metadata:
  author: langri-sha
  version: '1.0.0'
---

# Adapt

Change the agent without losing the conversation or making the user explain the
work again. Prepare a handoff, bring up the successor to your right, establish
that it can take over, then close only your own pane.

Read and use the `herdr` skill for Herdr app and TUI operations. It owns how to
identify panes, launch agents, communicate and manage their lifecycle. In tmux,
use its native pane operations. If the available tooling cannot carry out the
transfer safely, keep the source open and explain the gap.

Use the requested agent, model and effort; otherwise use the target agent's
configured defaults. Ask if the target agent is unclear. Preserve the task's
existing permissions and authorization.

## Modes

- `--dry-run`: inspect and describe the proposed transfer without changing state
  or launching anything.
- `--rehearse`: prepare the handoff and launch the successor to read and
  acknowledge it. Keep both panes open, with task work paused and ownership
  unchanged.
- No flag: complete the transfer. The request authorizes closing the source pane
  once the successor has taken over.

## Workflow

1. **Prepare to hand off.** Reach a sensible checkpoint and leave a durable
   brief where the successor can read it. Preserve the objective, decisions and
   their reasons, rejected approaches, unresolved questions, actual working
   state and next step. Include relevant artifacts and transcript references
   when they add context. Verify the current state rather than relying on
   recollection, and account for workers or jobs that still depend on you.

2. **Launch the successor.** Open a new pane immediately to your right in the
   appropriate working directory. Start the target agent independently of your
   lifetime and give it the handoff. It should read and verify the context
   before continuing work. This is a new conversation with context transferred,
   not a cross-harness session resume.

3. **Confirm understanding.** Have the successor explain where the work stands,
   what it would do next, and what still needs the user's decision. Resolve
   material gaps or contradictions before proceeding. A running process alone is
   not a successful handoff. In rehearsal, report the outcome and stop here;
   reuse that successor if later asked to complete the transfer.

4. **Transfer and close.** Make ownership explicit, including any ongoing
   workers and their results. Preserve the new session's recovery identity and
   its connection to the handoff; surface unsupported recovery rather than
   claiming it works. Once the successor accepts ownership, announce the
   transfer and close only the source pane. The successor continues the next
   authorized step, or waits if the work still needs a decision.

Keep the source available if the transfer fails. Only one agent owns the work at
a time; an uncertain handoff is a reason to reconcile ownership, not resume work
in both panes. Do not close the containing tab or window: that would also kill
the successor. In particular, `lights-out` currently has that wider scope.
