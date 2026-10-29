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
if missing, then execute tasks one at a time with progress tracked in the plan.

The plan lives with the work, inside the worktree:

- **Plan**: `.claude/PLAN.md`
- **Memory**: `.claude/memory.md`

Both are worktree-local and survive agent restarts — `/create-worktree` and
other orchestration skills resume from exactly these files. Never delete,
truncate, or "clean up" either file; archive instead (see below).

Keep them out of commits. If `git check-ignore -q .claude/PLAN.md` fails, append
`.claude/PLAN*.md` and `.claude/memory.md` to the file
`git rev-parse --git-path info/exclude` names: `.git/info/exclude` isn't a path
in a linked worktree.

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

## Phase 2: Generate the Plan

Ask the user for the goal and the requirements: what must be true when the work
is done. Draft the architecture and the tasks from the codebase, and confirm
them with the user before writing.

Create `.claude/` and an empty `.claude/memory.md` if they don't exist. If
`PLAN.md` already exists, ask before appending the new plan below a separator.
Write `.claude/PLAN.md` in this shape:

```markdown
# Implementation Plan: <title>

<One or two sentences on what the plan accomplishes.>

## Hand-off protocol

Each task runs in a sub-agent, which before reporting back:

1. Records decisions, discoveries and notes for the next agent in
   `.claude/memory.md`, under `## Task <n>: <name>`.
2. Commits the work with `/create-commit`.
3. Reviews the diff and addresses what it finds, noting anything unresolved in
   memory.
4. Checks the task off in this plan.

## Requirements

- 1.1 <requirement>

## Architecture

<Components and how they interact; an ASCII diagram if it helps.>

## Tasks

### 1. <Section>

- [ ] 1.1 <Task>: <details, files to create or change>. _Requirements: 1.1_

### 2. Checkpoint: <section>

- [ ] 2. Verify <section> works: <steps>. Ask the user if questions arise.

## Follow-up

- [ ] <Out of scope for now>
```

Number sections 1, 2, 3 and tasks within them 1.1, 1.2. Each task has one clear
outcome. Put a checkpoint after each functional section, such as setup, the API
layer, the UI and the wiring, and end with an end-to-end check.

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
