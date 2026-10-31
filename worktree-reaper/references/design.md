# Worktree Reaper: Design

Why the reaper works the way it does, and how to test it. SKILL.md holds the
runtime contract.

## Where the Space Actually Goes

Git objects live once in `.bare/` and are shared by every worktree. Removing a
worktree therefore reclaims its **checked-out files only** — `node_modules`,
build output, caches, and other ignored or untracked files. History is never at
stake, and no branch is deleted. That is why a 2 GiB worktree can be removed and
recreated later with `/create-worktree` at the cost of one `pnpm install`.

## What Patch-Equivalence Does Not Prove

`git cherry` proves a branch's commits **appear in the primary's history**, not
that the primary's **current tree** still contains them. If a change landed and
was later reverted, a branch carrying that change still reads as landed, because
its upstream twin is right there in the history. A merged-PR lookup does not
save you either — the PR really was merged; the revert came after.

The blast radius is bounded and worth stating plainly: removal never deletes a
branch, so the commits survive and the worktree comes back with
`git worktree add <path> <branch>`. What you lose is the directory and the
`pnpm install` in it.

A final-state check was tried and rejected: `git merge-tree --write-tree`
against the primary answers the revert case correctly, but conflicts on old
branches whose work landed long ago and whose files have since moved on — two of
the three real candidates in this garden — so it trades a rare false positive
for common false negatives. The fixture harness pins the revert case so the
behaviour stays visible rather than surprising.

## Empty Commits

A commit that changes no files is a normal part of this workflow —
`Retrigger CI`, or a commit recording an action taken outside the repo like a
Terraform apply. Rebase-merge **drops** them, so they never reach `origin/main`,
while the branch ref keeps them forever because nothing rewrites a branch after
its PR merges.

`git cherry` decides "already upstream" by patch-id, and a commit with no diff
has no patch to match. Such a commit is therefore structurally `+` —
permanently, no matter what landed. A commit-for-commit rule would let one
deliberate no-op veto an entire branch forever: when this skill shipped, all
three genuinely reclaimable worktrees in the garden were held back by exactly
one such commit each, so the default mode could never fire.

So the question asked is "is every _change_ accounted for upstream?", not "is
every _commit_?". A commit whose tree matches its parent's demonstrably alters
nothing and cannot carry unlanded work, so it does not hold a worktree back.
Candidates say so in their evidence (`1 empty commit(s) ignored`).

`--strict-commits` restores the commit-for-commit rule if you want it. Be aware
of what it means in practice: any branch that ever needed a CI retrigger stays
skipped, however completely its work landed.

## One Classifier

Apply re-runs the full classifier on every candidate right before removal. The
gate that approves a removal is the same code that produced the report — there
is no second, weaker set of checks to drift out of sync.

## Cost of a Dry Run

The dry report is cheap — about 4 seconds over 65 worktrees, plus `du` on the
candidates — and mutates nothing, so it is safe to run on a schedule.

## Tests

A standalone fixture harness builds a throwaway garden in a temp directory and
covers every classification branch — rebase-merged, patch-equivalent, empty
retrigger commit, unmerged, dirty, untracked, ignored-only, detached, locked,
in-use (a Herdr TUI pane, tab or workspace, and an hc terminal, tab or space,
through stub `herdr` and `hc` binaries), nested, out-of-garden, stale, and the
protected trio:

```bash
tests/run-tests.sh
```

It asserts that dry runs change nothing, that apply removes only the landed and
idle worktrees, that branches and the bare repo survive, and that prune runs
only after a successful removal. It never touches a real garden. Run it after
changing `reap.sh`.
