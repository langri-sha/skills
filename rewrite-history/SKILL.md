---
name: rewrite-history
description:
  Use this skill when the user says "rewrite history" or wants to reorganize
  messy changes or WIP commits into clean, atomic commits that tell a logical
  story.
---

# Rewrite History

Change the commits, never the code: the new history ends on exactly the tree it
started from. Nothing is pushed unless the user asks.

Neither Claude Code nor Codex keeps shell variables between commands. Step 1
runs as one command and prints three values; write them literally wherever
`<base>`, `<snapshot>` and `<sandbox>` appear later.

## 1. Snapshot and sandbox

Capture the user's state, including uncommitted and untracked files, without
touching their index or working tree, then open a detached worktree on it:

```bash
TRUNK=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name)
git fetch origin "$TRUNK"
BASE=$(git merge-base "origin/$TRUNK" HEAD)  # $(git rev-parse HEAD) to organize only uncommitted work
IDX=$(mktemp -u)                             # git must create the index itself
GIT_INDEX_FILE=$IDX git read-tree HEAD
GIT_INDEX_FILE=$IDX git add -A
SNAPSHOT=$(git commit-tree "$(GIT_INDEX_FILE=$IDX git write-tree)" -p HEAD \
  -m 'Snapshot before history rewrite')
rm -f "$IDX"
SANDBOX=$(mktemp -d)
git worktree add --detach "$SANDBOX" "$SNAPSHOT"
git -C "$SANDBOX" reset "$BASE"              # the whole change is now unstaged
printf 'base=%s\nsnapshot=%s\nsandbox=%s\n' "$BASE" "$SNAPSHOT" "$SANDBOX"
```

The snapshot is the recovery point. Install dependencies in the sandbox so hooks
and checks run.

## 2. Plan the story

Propose the commit subjects in order, each with its files or hunks, and the
untracked files to leave out, such as scratch notes or local env files. Wait for
the user to approve both. The split follows `create-commit`:

- one decision per commit that a reviewer could accept or question on its own;
- dependencies before the code that uses them;
- tests in the same commit as the code they cover;
- refactoring and formatting apart from behavior changes;
- plain imperative subjects, with no type prefixes.

Size and shared files are never reasons to combine. Stop splitting only where a
commit would fail its checks or be separated from its tests.

## 3. Build it

Stage each step with `git -C <sandbox> add <path>`. For a file that spans steps,
write the exact patch and `git -C <sandbox> apply --cached` it: interactive
`git add -p` doesn't work in an agent shell. Commit each step and run the repo's
checks on it. A commit that fails is a planning error, so regroup rather than
keep a broken intermediate.

## 4. Prove it

```bash
git -C <sandbox> diff --exit-code <snapshot> HEAD -- . ':!<left-out path>'
```

Add one `':!<path>'` per approved leave-out. Any output means code was lost or
changed. Stop and report it; don't deliver.

## 5. Deliver

```bash
git -C <sandbox> branch <branch>-rewritten HEAD
git worktree remove --force <sandbox>
```

`--force` is needed because the left-out files are still in the sandbox; the
user's own copies stay put. Show the new log. Moving the user's branch is their
call. First check that their working tree still matches the snapshot:

```bash
IDX=$(mktemp -u); GIT_INDEX_FILE=$IDX git read-tree HEAD; GIT_INDEX_FILE=$IDX git add -A
[ "$(GIT_INDEX_FILE=$IDX git write-tree)" = "$(git rev-parse '<snapshot>^{tree}')" ] && echo unchanged
rm -f "$IDX"
```

- If unchanged, `git reset <branch>-rewritten` moves the branch without touching
  any file on disk, and left-out files stay untracked.
- If it has moved on, leave the new branch for them to adopt.

Push, or `--force-with-lease` a branch that was already pushed, only when the
user asks.
