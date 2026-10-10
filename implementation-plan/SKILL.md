---
name: implementation-plan
description:
  Resolve the current worktree's plan and either continue it or generate a new
  one, then conduct task-by-task execution. Use for lightweight plan
  entrypoints. Triggers on "implementation plan", "create a plan", "plan this
  feature", or "/implementation-plan".
metadata:
  author: langri-sha
  version: '2.0.0'
---

# Implementation Plan

Conduct plan-driven work in the current worktree: locate the plan, generate one
if missing (via `/implementation-plan-generate`), then execute tasks one at a
time with progress tracked in the plan.

The plan lives with the work, inside the worktree:

- **Plan**: `.claude/PLAN.md`
- **Memory**: `.claude/memory.md`

Both are worktree-local (the repo gitignores `.claude/*` beyond the tracked
skills) and survive agent restarts — `/create-worktree` and `/orchestrate-epic`
resume from exactly these files. Never delete, truncate, or "clean up" either
file; archive instead (see below).

Note: the command is `/implementation-plan` (not `/implement-plan`).

## Phase 1: Resolve the Plan

Work from the worktree the plan belongs to:

```bash
TOPLEVEL=$(git rev-parse --show-toplevel)
```

- If the user is targeting a different worktree, recommend they switch there
  first — the plan must live in the worktree it drives.
- If `$TOPLEVEL/.claude/PLAN.md` exists, summarize its progress (tasks done /
  total) and offer to continue. If the user wants a fresh start instead, archive
  the old plan to `.claude/PLAN-<UTC-timestamp>.md.bak` before generating a new
  one.
- If there is no plan, proceed to Phase 2.
- Legacy location: older plans lived at `~/agents/<repo>/<worktree>/PLAN.md`. If
  no worktree plan exists but a legacy one does, offer to copy it into
  `.claude/` and continue from there.

## Phase 2: Generate the Plan

Invoke `/implementation-plan-generate`. It gathers requirements and writes
`.claude/PLAN.md` (and creates `.claude/memory.md` if missing).

## Phase 3: Conduct Execution

Act as the conductor: delegate tasks to sub-agents and track progress.

1. **Identify the next task** — the first unchecked `[ ]` item in PLAN.md. Read
   its description and requirements, and read `.claude/memory.md` for decisions
   and discoveries from earlier tasks.

2. **Delegate to a sub-agent** — brief it with the specific task, the plan's
   architecture section, the hand-off protocol, and any relevant memory notes.
   Use a design-oriented agent for design tasks and a general-purpose agent for
   implementation.

3. **Hand-off protocol (the sub-agent must complete all of these):**
   - Append decisions, discoveries, and notes for the next agent to
     `.claude/memory.md`
   - Commit the completed task with `/create-commit`
   - Review the diff (e.g. `/code-review`) and address findings
   - Mark the task `[x]` in PLAN.md
   - Report results back

4. **Review the hand-off** — verify the protocol was followed: memory updated,
   commit created, task checked off. Surface the result to the user and ask
   whether to continue.

**Only the user approves moving to the next task.** Do not loop autonomously
unless the user has explicitly said to run through multiple tasks.
