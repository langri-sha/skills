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
- Wants a messy branch to read as a sequence of logical steps.
- Says "make this look like a story".

To split a large change or PR into a stack of separate, independently reviewable
PRs, use `split-pr-stack` instead — this skill rewrites the local commit story
on a single branch and never creates PRs.

## Core Workflow

Neither Claude Code nor Codex keeps shell variables between commands. Step 1
runs as one command and prints the values the later steps need; write them
literally wherever `<snapshot>` and `<sandbox>` appear.

### Step 1: Safe Sandbox Creation

**Goal:** Perform all destructive operations in isolation to prevent data loss.

1.  **Define the Scope:** the base is the merge base with the trunk when
    rewriting commits, or `HEAD` when only uncommitted work needs organizing.

2.  **Snapshot and Sandbox:** capture the user's state, uncommitted and
    untracked files included, without touching their index or working tree, then
    open a detached worktree on it with the whole change unstaged:

    ```bash
    IDX=$(mktemp -u)                       # git must create the index itself
    GIT_INDEX_FILE=$IDX git read-tree HEAD
    GIT_INDEX_FILE=$IDX git add -A
    SNAPSHOT=$(git commit-tree "$(GIT_INDEX_FILE=$IDX git write-tree)" -p HEAD \
      -m 'Snapshot before history rewrite')
    rm -f "$IDX"
    SANDBOX_DIR=$(mktemp -d -t rewrite-history-XXXXXX)
    git worktree add --detach "$SANDBOX_DIR" "$SNAPSHOT"
    git -C "$SANDBOX_DIR" reset <base-sha>
    printf 'snapshot=%s\nsandbox=%s\n' "$SNAPSHOT" "$SANDBOX_DIR"
    ```

    The snapshot is the recovery point. Inside the sandbox `HEAD` is the
    snapshot, so pass the base as a SHA.

### Step 2: Analysis and Storyboarding

**Goal:** Understand the changes and plan the narrative.

1.  **Draft the Storyboard:** propose the commits in order, each with its files
    or hunks. The split follows `create-commit`:
    - one decision per commit that a reviewer could accept or question on its
      own;
    - dependencies before the code that uses them;
    - tests in the same commit as the code they cover;
    - refactoring and formatting apart from behavior changes;
    - plain imperative subjects, with no type prefixes.

    Size and shared files are never reasons to combine. Stop splitting only
    where a commit would fail its checks or be separated from its tests.

2.  **Identify Orthogonal Chunks (Parallel Merge Opportunities):**
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

- **Present the Plan:** Show the user the list of proposed commits, and the
  untracked files to leave out of history, such as scratch notes or local env
  files.
- **Iterate:** Allow the user to combine, split, or rename commits.
- **Approval:** "Does this story look correct?"

### Step 4: Execution (The "Crafting")

**Goal:** Build the history commit by commit.

For each step in the approved plan:

1.  **Stage Specific Changes:**
    - **File-level:** `git -C <sandbox> add path/to/file`
    - **Hunk-level (Advanced):** Use `git apply` with crafted patches for
      partial file commits.
2.  **Verify Atomicity:**
    - Can you describe the commit in one clear sentence?
    - Does it accomplish a complete logical unit?
    - Are tests and implementation together (if applicable)?
3.  **Commit** following the `/create-commit` message conventions (imperative
    subject, body explains what and why, refs in the body):

    ```bash
    git -C <sandbox> commit -m "$(cat <<'EOF'
    Subject line in imperative mood

    Body explaining what changed and why.
    EOF
    )"
    ```

### Step 5: Final Verification

**Goal:** Ensure no code was lost or corrupted.

1.  **Compare End States:**

    ```bash
    # Compare the sandbox HEAD with the snapshot
    git -C <sandbox> diff --exit-code <snapshot> HEAD -- . ':!<left-out path>'
    ```

    Add one `':!<path>'` per approved leave-out; the snapshot holds them, the
    new history doesn't.

2.  **Outcome:**
    - **Empty Diff:** Success! The code is identical, only history changed.
    - **Non-Empty:** Failure. Abort and report differences.

### Step 6: Delivery

**Goal:** Apply the new history to the user's workspace — locally. Do not push
anywhere unless the user explicitly asks.

1.  **Create a local branch on the crafted history:**

    ```bash
    # Name the result so it survives worktree removal
    git -C <sandbox> branch crafted-history HEAD
    ```

2.  **Cleanup:**

    ```bash
    git worktree remove --force <sandbox>
    ```

    `--force` is needed because the left-out files are still in the sandbox; the
    user's own copies stay where they are.

3.  **User Action:**
    - Offer to `git reset --hard crafted-history` on the original branch (only
      after the Step 5 verification diff came back empty).
    - Or leave `crafted-history` for the user to inspect and adopt themselves.
    - Pushing (and any `--force-with-lease` update of a remote branch) happens
      only on the user's explicit say-so.

## Best Practices for "Storytelling"

1.  **Dependency Order:** Always commit dependencies (libraries, base classes)
    before the code that uses them.
2.  **Separation of Concerns:** Never mix formatting changes (prettier/lint)
    with logic changes.
3.  **Test Inclusion:** Commit tests in the same commit as the code they cover.

## Troubleshooting

- **"Hunk overlap":** If two logical changes are too close in the same file,
  manual intervention might be needed.
- **"Build failure":** If a commit in the middle of the chain breaks the build,
  ask the user if they care about "green" intermediate commits or just the final
  result.
