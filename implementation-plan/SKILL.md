---
name: implementation-plan
description:
  Resolve plan/memory paths and decide whether to continue an existing plan or
  generate a new one. Use for lightweight plan entrypoints. Triggers on
  "implementation plan", "create a plan", "plan this feature", or
  "/implementation-plan".
metadata:
  author: langri-sha
  version: '1.0.0'
---

# Implementation Plan (Lightweight)

This skill resolves the plan/memory location, checks for an existing plan, and
decides whether to continue or generate a new plan. For plan generation, call
`/implementation-plan-generate`.

Note: the command is `/implementation-plan` (not `/implement-plan`).

## Phase 0: Resolve Plan/Memory Path

Resolve the plan/memory location before anything else.

**Default path rule (current worktree):**

- If current path matches `~/workspace/<repo>.worktree/<worktree>/...`, then:
  - `<repo>` = part before `.worktree`
  - `<worktree>` = next path segment after `<repo>.worktree`
  - Plan path: `~/agents/<repo>/<worktree>/PLAN.md`
  - Memory upath: `~/agents/<repo>/<worktree>/MEMORY.md`

If the user started in a directory that is not the worktree source, recommend
they exit and `cd` into the worktree before proceeding.

**If user provides a `<worktree>` slug instead of a path:**

- Search `~/agents/*/<worktree>/` and use the match.
- If multiple matches exist, ask the user to pick one.

If neither rule can resolve a path, ask the user for the full
`~/agents/<repo>/<worktree>/` path.

## Phase 1: Check for Existing Plan

Check if `PLAN.md` already exists in the resolved location.

- Ensure the directory exists first:
  - Create `~/agents/<repo>/<worktree>/` if missing.
- Ensure the memory file exists:
  - Create `MEMORY.md` if missing.

- If a plan exists:
  - Offer to continue with the existing plan.
  - If they want a fresh start, archive `PLAN.md` to `PLAN.md.bak` with a
    timestamp in the same folder, then proceed to plan generation.
- If no plan exists:
  - Proceed to plan generation.

## Phase 2: Generate Plan

When a new plan is needed, invoke `/implementation-plan-generate`.

Then, call /worktree-generate to create the new worktree and recommend the user
to exit and change directory to it:

```
Please use /exit, then ru n:

cd ~/workspace/<repo>.worktree/<worktree>
claude --resume <session id>
```
