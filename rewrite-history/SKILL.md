---
name: rewrite-history
description:
  Use this skill when the user says "rewrite history" or wants to reorganize
  messy changes or WIP commits into clean, atomic commits that tell a logical
  story.
---

# Rewrite History

## Overview

This skill transforms a "messy" state (a large set of uncommitted changes or a
series of "wip" commits) into a clean, linear history. It treats the commit log
as a narrative, ensuring each commit represents a single, complete logical unit
(atomic commit). All operations are performed in a temporary worktree to safely
build the new history without disrupting the user's current workspace.

## When to Use This Skill

Invoke this skill when the user:

- Has a lot of uncommitted work and wants to "save it" cleanly.
- Asks to "clean up my history" or "organize these changes".
- Wants to split a massive PR into logical steps.
- Says "make this look like a story".

## Core Workflow

### Step 1: Safe Sandbox Creation

**Goal:** Perform all destructive operations in isolation to prevent data loss.

1.  **Define the Scope:**
    - If working with uncommitted changes: Target is `HEAD`.
    - If rewriting history: Target is the merge base (e.g., `main`).

2.  **Create Worktree:**

    ```bash
    # Create a temporary directory
    SANDBOX_DIR=$(mktemp -d -t rewrite-history-XXXXXX)

    # Create a detached worktree at the current state
    git worktree add --detach "$SANDBOX_DIR" HEAD
    ```

3.  **Flatten the State (The "Canvas"):** Inside the sandbox, reset the state to
    the base so all changes appear as "new work" to be organized.
    ```bash
    cd "$SANDBOX_DIR"
    # Soft reset to the base branch to stage all changes
    git reset --soft <base-branch>
    # Unstage everything to start with a clean slate
    git reset HEAD
    ```

### Step 2: Analysis and Storyboarding

**Goal:** Understand the changes and plan the narrative.

1.  **Analyze Diffs:**
    - Run `git diff` to see all changes.
    - Group changes by:
      - **Infrastructure:** Config files, build scripts, `.gitignore`.
      - **Core Logic:** Models, utilities, backend logic.
      - **Features:** UI components, routes, business logic.
      - **Tests:** Unit/Integration tests.
      - **Documentation:** README, comments.

2.  **Draft the Storyboard:** The agent proposes a sequence of commits.

    _Example Plan:_
    1.  `chore(deps): add doctron dependencies` (package.json, pnpm-lock.yaml)
    2.  `feat(core): implement basic agent architecture` (src/agent.ts,
        src/types.ts)
    3.  `feat(prompts): add system prompts for code review` (src/prompts/\*.md)
    4.  `test: add initial agent tests` (tests/agent.test.ts)

3.  **Identify Orthogonal Chunks (Parallel Merge Opportunities):**
    - Check if the changes contain independent groups of commits (orthogonal
      chunks) that could be merged in parallel (e.g., unrelated features,
      distinct fixes).
    - If identified, present each chunk to the user using this format:

      ```
      <PR title>

      <A concise description of what is changing, 1-2 sentences max.>

      <List of commits>
      ```

### Step 3: Interactive Review

**Goal:** Get user buy-in on the narrative.

- **Present the Plan:** Show the user the list of proposed commits.
- **Iterate:** Allow the user to combine, split, or rename commits.
- **Approval:** "Does this story look correct?"

### Step 4: Execution (The "Crafting")

**Goal:** Build the history commit by commit.

For each step in the approved plan:

1.  **Stage Specific Changes:**
    - **File-level:** `git add path/to/file`
    - **Hunk-level (Advanced):** Use `git apply` with crafted patches for
      partial file commits.
2.  **Verify Atomicity:**
    - Can you describe the commit in one clear sentence?
    - Does it accomplish a complete logical unit?
    - Are tests and implementation together (if applicable)?
3.  **Commit:**
    ```bash
    git commit -m "<type>(<scope>): <description>" -m "<body>"
    ```

### Step 5: Final Verification

**Goal:** Ensure no code was lost or corrupted.

1.  **Compare End States:**
    ```bash
    # Compare the sandbox HEAD with the original user HEAD
    git diff HEAD <original-user-head-sha>
    ```
2.  **Outcome:**
    - **Empty Diff:** Success! The code is identical, only history changed.
    - **Non-Empty:** Failure. Abort and report differences.

### Step 6: Delivery

**Goal:** Apply the new history to the user's workspace.

1.  **Push/Fetch:**

    ```bash
    # Push the new history to a temp branch on origin
    git push origin HEAD:refs/heads/<type>/<branch-name>
    ```

2.  **Cleanup:**

    ```bash
    # Remove the worktree
    cd <original-dir>
    git worktree remove "$SANDBOX_DIR" --force
    ```

3.  **User Action:**
    - Offer to `git reset --hard agent/crafted-history` (if safe).
    - Or simply leave the branch for the user to inspect.

## Best Practices for "Storytelling"

1.  **Dependency Order:** Always commit dependencies (libraries, base classes)
    before the code that uses them.
2.  **Separation of Concerns:** Never mix formatting changes (prettier/lint)
    with logic changes.
3.  **Test Inclusion:** Ideally, commit tests alongside the feature they test
    (TDD style), or immediately after.

## Troubleshooting

- **"Hunk overlap":** If two logical changes are too close in the same file,
  manual intervention might be needed.
- **"Build failure":** If a commit in the middle of the chain breaks the build,
  ask the user if they care about "green" intermediate commits or just the final
  result.
