# Snapshot, replay, and equivalence proof

The mechanics that make a stack split recoverable and provably lossless. Record
every SHA in the handoff manifest.

| Name            | Meaning                                                  |
| --------------- | -------------------------------------------------------- |
| `SOURCE_HEAD`   | Tip commit of the source branch at inspection time       |
| `SOURCE_BASE`   | `git merge-base` of the source and the pinned trunk      |
| `TRUNK_SHA`     | Pinned `origin/<trunk>` at inspection time               |
| `SNAPSHOT`      | Safety commit capturing the exact source worktree        |
| `REFERENCE_SHA` | The approved source delta replayed once onto `TRUNK_SHA` |
| `TOP`           | Tip of the highest stack branch                          |

## Safety snapshot (dirty worktree)

A temporary index captures tracked and non-ignored untracked content without
touching the real index, working files, branch, or remote:

```bash
SOURCE_HEAD=$(git rev-parse HEAD)
TMP_INDEX=$(mktemp)
rm -f "$TMP_INDEX"                    # Git must create the index itself

GIT_INDEX_FILE="$TMP_INDEX" git read-tree "$SOURCE_HEAD"
GIT_INDEX_FILE="$TMP_INDEX" git add -A
TREE=$(GIT_INDEX_FILE="$TMP_INDEX" git write-tree)
SNAPSHOT=$(printf '%s\n' 'Safety snapshot before stack split' |
  git commit-tree "$TREE" -p "$SOURCE_HEAD")

git update-ref "refs/heads/safety/<stack-slug>-source-<timestamp>" "$SNAPSHOT"
rm -f "$TMP_INDEX"

git diff --exit-code "$SNAPSHOT" --   # empty = captured exactly
```

Ignored files stay excluded, as they should be from any PR. Print the ref and
the recovery command before proceeding:

```bash
# restore the captured state onto a clean checkout of SOURCE_HEAD
git diff --binary <SOURCE_HEAD> <SNAPSHOT> | git apply
```

For a clean, fully committed branch the snapshot is simply a safety ref at
`SOURCE_HEAD`.

**Stop rather than improvise** when sparse checkout, submodule-local changes,
intent-to-add entries, unusual index extensions, or required-but-ignored
artifacts make the capture ambiguous.

## Reference replay — once, onto the pinned trunk

Do not split on the old ancestry and resolve the same trunk conflicts layer by
layer. Replay the whole delta once:

```bash
# in the stack worktree, detached at the pinned trunk
git switch --detach "$TRUNK_SHA"
git diff --binary "$SOURCE_BASE" "$SNAPSHOT" | git apply --3way
```

- Any conflict → stop for human resolution. Never guess through semantic
  conflicts, migration ordering, generated artifacts, or lockfiles.
- Commit the approved result to `safety/<stack-slug>-reference`; record
  `REFERENCE_SHA`.
- If the trunk has not moved past `SOURCE_BASE`, the reference tree should equal
  the snapshot tree — verify with `git diff <SNAPSHOT> <REFERENCE_SHA>` and
  treat any difference as a conflict to explain. If the trunk did move, document
  every resolution and intentional adaptation.

The reference — not the original branch — is the contract the stack must
reproduce.

## Materializing the layers

Start each stack branch where the previous one ended; carry the residual forward
uncommitted:

```bash
git switch -c <stack-slug>-01-<layer> "$TRUNK_SHA"
git diff --binary "$TRUNK_SHA" "$REFERENCE_SHA" | git apply
# worktree = reference tree, index = trunk: everything is unstaged residual

# layer 1: stage only its slice
git add path/a path/b                 # whole files
git apply --cached layer-1-extra.patch # exact patch for a file spanning layers
git commit                            # /create-commit conventions

git switch -c <stack-slug>-02-<layer> # same HEAD; residual carries forward
# stage layer 2, commit, repeat until the residual is empty
```

- Never interactive `git add -p`; craft the patch, inspect it, and apply it to
  the index with `git apply --cached`.
- Overlapping or ambiguous hunks are a stop condition, not a judgment call.
- After the final commit the residual must be empty: `git status --porcelain`
  prints nothing. Anything left is an unassigned change — the plan was
  incomplete.
- Multiple commits inside a layer are fine when they serve the same concern and
  each leaves the tree valid.

## Proof obligations

All of these must pass before Gate C:

```bash
# 1. Exact end state: the top branch tree equals the reference tree
git diff --exit-code "$REFERENCE_SHA" "<top-branch>"

# 2. Strict linear ancestry for every adjacent pair
git merge-base --is-ancestor "<parent-branch>" "<child-branch>"

# 3. No whitespace-error regressions per layer
git diff --check "<parent-branch>".."<child-branch>"
```

Then run the repository's required checks per layer, bottom-up, each on a clean
checkout:

```bash
for branch in <branch-01> <branch-02> <branch-03>; do
  git switch "$branch"
  git status --porcelain              # must be empty
  pnpm dagger:check                   # or the repo's documented required gates
done
```

Targeted tests are a useful addition but never a substitute for the repository's
required checks. For migrations and infrastructure, also validate
forward/backward compatibility and plan output per layer. A layer that only
becomes buildable when a future layer exists is invalid and must be redesigned.

## Pre-publication drift check

Immediately before any push:

```bash
git fetch origin
git rev-parse "origin/<trunk>"          # must equal TRUNK_SHA, or re-plan
git ls-remote origin "<source-branch>"  # source remote head unchanged
git ls-remote origin "<stack-slug>-*"   # no target branch already exists
```

If the trunk moved: rebase the stack locally, rerun every affected layer's
checks, produce a fresh reference proof, and get it re-approved before
publishing.
