---
name: implementation-plan-generate
description:
  Gather requirements and generate a structured implementation plan with
  requirements, architecture, tasks, and hand-off protocol. Use after the plan
  path is resolved and a new plan is needed. Triggers on
  "/implementation-plan-generate".
metadata:
  author: langri-sha
  version: '1.0.0'
---

# Implementation Plan Generator

Create a comprehensive `~/agents/<repo>/<worktree>/PLAN.md` document through
guided questions. The skill actively helps break down requirements into
hierarchical tasks with checkpoints after each major section.

Before writing the plan, ensure `~/agents/<repo>/<worktree>/` exists and create
`MEMORY.md` if it does not exist yet. Never delete, truncate, or "clean up"
`PLAN.md` or `MEMORY.md`; these files are append-only for harvesting.

Repo naming: derive `<repo>` via `basename -s .git $(git remote get-url origin)`
when a Git remote is available.

## Workflow

### Phase 1: Gather Information

Use AskUserQuestion to collect:

1. **Feature/Goal** (required)
   - "What feature or goal are you implementing?"
   - "Provide a 1-2 sentence description for the plan title."

2. **Requirements** (required)
   - "List the high-level requirements (one per line)."
   - "What must be true when this is complete?"

3. **Architecture Overview** (optional but recommended)
   - "Describe the main components and how they interact."
   - "Any existing patterns to follow?"
   - Offer to help generate an ASCII architecture diagram.

4. **Initial Task Ideas** (optional)
   - "Any specific tasks you already know need to happen?"
   - "What's the first thing that needs to be built?"

5. **Agent Hand-off Customization** (optional)
   - "Any project-specific notes for the hand-off protocol?"
   - Default memory location: `~/agents/<repo>/<worktree>/MEMORY.md`

### Phase 2: Generate Plan

After gathering requirements and architecture, generate the full plan content
using the structure below.

### Phase 3: Write Plan

Write the plan to `~/agents/<repo>/<worktree>/PLAN.md` with this structure. If
`PLAN.md` already exists, then stop and ask the user if they actually want to
continue. If they do, then just append to `PLAN.md` the new plan with a clear
separator.

````markdown
# Implementation Plan: [Feature Title]

[1-2 sentence description of what this plan accomplishes]

## Agent Hand-off Protocol

Each task is executed by a sub-agent. Before completing, agents MUST:

1. **Update memory** - Record context in `~/agents/<repo>/<worktree>/MEMORY.md`
2. **Create atomic commit** - Run `/create-commit` for completed work
3. **Review changes** - Run `/review` to verify code quality
4. **Mark task complete** - Check off the task in this plan
5. **Wait for user** - Consult user if they want to make changes before
   continuing

**Memory location:** `~/agents/<repo>/<worktree>/MEMORY.md`

**What to record:**

- Design decisions made and rationale
- Unexpected findings or gotchas
- Patterns discovered in the codebase
- Deviations from the plan and why

**Memory format:**

```markdown
## Task X.X: [Task Name]

**Agent:** [timestamp]

### Decisions

- [Decision made and why]

### Discoveries

- [Unexpected finding or gotcha]

### Notes for next agent

- [Anything the next agent should know]
```
````

**Commit protocol:**

- Each task = one atomic commit (unless trivially small)
- Use `/create-commit` to generate commit with proper message
- Commit message should reference task number (e.g., "Task 1.2: Add popover
  component")

**Review protocol:**

- Run `/review` before marking task complete
- Address any issues found before hand-off
- Note unresolved issues in memory for next agent

[Project-specific hand-off notes if provided]

## Requirements

- 1.1 [Requirement description]
- 1.2 [Requirement description]
- 2.1 [Requirement description]

## Architecture

```
[ASCII diagram if provided/generated]
```

[Component descriptions]

## Implementation Tasks

### 1. [Section Name]

- [ ] 1.1 [Task description]
  - [Implementation details]
  - [File paths to create/modify]
  - _Requirements: X.X_

- [ ] 1.2 [Task description]
  - [Details]
  - _Requirements: X.X_

### 2. Checkpoint - [Section Name]

- [ ] 2. Checkpoint - Verify [section] works
  - [Verification steps]
  - Ask user if questions arise

[Continue pattern...]

## Follow-up Tasks

- [ ] [Future enhancement]
- [ ] [Nice-to-have out of scope]

```

## Task Numbering Convention

- Major sections: 1, 2, 3...
- Tasks within sections: 1.1, 1.2, 1.3...
- Checkpoints get their own major number
- Keep numbers sequential even when sections vary in size

## Checkpoint Pattern

Insert checkpoints after each major functional section:
- After setup/dependencies
- After API/backend layer
- After UI components
- After integration/wiring
- Final end-to-end verification

Each checkpoint should:
- Verify the section's deliverables work
- List specific test steps
- Include "Ask user if questions arise"

## Tips for Good Plans

- Tasks should be atomic (one clear outcome, one commit)
- Include file paths where known
- Reference requirements for traceability
- Checkpoints prevent drift on long implementations
- Follow-up section captures scope creep productively
```
