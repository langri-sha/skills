---
name: split-pr-stack
description: >-
  Split a large change or existing pull request into a dependency-ordered stack
  of small, standalone, independently reviewable draft PRs. Preserves the
  original branch and PR by default, proves exact end-state equivalence between
  the original change and the assembled stack, validates every layer
  independently, and never merges. Use when the user says "/split-pr-stack",
  "split this PR into a stack", "break this change into reviewable PRs", or
  wants to review a large PR one piece at a time.
metadata:
  author: langri-sha
  version: '1.0.0'
  argument-hint: >-
    [PR number | branch] [--base <branch>] [--plan-only | --materialize-local |
    --publish-drafts]
---

# Split PR Stack

Turn an oversized PR or a heavy worktree into an ordered stack of small,
standalone PRs that a human can review one at a time. The skill plans the
decomposition, snapshots the source, rebuilds the change as dependency-ordered
local branches, proves the assembled stack reproduces the original end state
exactly, validates every layer independently, and publishes the result as draft
PRs — every mutation class behind an explicit approval gate.

This skill orchestrates; it never lands anything. The terminal state is a
validated local stack or a set of verified draft PRs plus a handoff manifest.
Landing is a separate, human-driven step.

## Safety contract

Enforce all of these, in every mode:

1. **Read-only until Gate A.** Inspection, layer planning, and a proposed action
   manifest come first; no branch, commit, worktree, push, PR, or API mutation
   before the plan is approved.
2. **Recoverable source.** A local safety ref captures the complete source
   worktree — including non-ignored untracked files — before any reconstruction.
3. **Original preserved.** The source branch and PR are never rewritten,
   retargeted, force-pushed, closed, or commented on by default. The stack is
   built in parallel; the human decides the original's fate after the stack is
   accepted.
4. **Pinned baseline.** Source head, source base, trunk, snapshot, and reference
   SHAs are recorded before reconstruction and re-verified before publication.
5. **Exact end-state equivalence.** The top of the stack must have the same tree
   as the approved reference replay: `git diff --exit-code` between the two is
   empty, or the skill stops.
6. **Every layer green.** Each branch is checked out cleanly and passes the
   repository's required checks on its own. A layer that only works once a later
   layer exists is invalid.
7. **Linear, explicit ancestry.** Each branch tip contains the previous branch
   tip; no merge commits, no skipped dependencies.
8. **Draft-first publication.** Remote output is draft PRs. Ready-for-review,
   reviewer requests, and any edit to the original PR each require their own
   approval.
9. **One worktree per stack.** Layers are branches inside a single stack
   worktree — never one worktree per layer (Git will not check out one branch in
   two worktrees anyway).
10. **No merging, ever.** Not with `gh pr merge`, not with `gh stack merge`, not
    via auto-merge or admin bypass. Landing belongs to a human.
11. **Non-interactive stack commands only.** Never `gh stack modify`, `switch`,
    or a bare `init`, `submit` or `view`; always the forms with explicit flags.

## Arguments and modes

| Argument | Required | Description                                                                                                                                                        |
| -------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `source` | no       | PR number, branch name, or worktree path. Defaults to the current worktree's branch and its open PR, if any. If an argument could be either a PR or a branch, ask. |
| `--base` | no       | Trunk the stack targets. Defaults to the repository default branch.                                                                                                |
| mode     | no       | `--plan-only` (default), `--materialize-local`, or `--publish-drafts`.                                                                                             |

Modes are monotonic approval boundaries, not shortcuts — `--publish-drafts`
still performs every earlier phase and stops at every gate:

- **`--plan-only`** — phases 0–1: inspect and produce the layer manifest.
  Nothing is created, not even the safety ref.
- **`--materialize-local`** — through phase 4: snapshot, reference replay, local
  branches, per-layer validation, equivalence proof. No remote mutation.
- **`--publish-drafts`** — through phase 5: push the stack and open draft PRs
  after Gate C.

## Approval gates

| Gate                | Human approves                                                              | The skill may then                                        | Still forbidden                                                      |
| ------------------- | --------------------------------------------------------------------------- | --------------------------------------------------------- | -------------------------------------------------------------------- |
| A — plan            | Layer manifest; creating the safety snapshot                                | Create safety ref, stack worktree, reference replay       | Any remote mutation; touching the original branch                    |
| B — reference       | Conflict resolutions; the full reference diff                               | Materialize ordered local branches; local `gh stack init` | Any remote mutation                                                  |
| C — publish         | Exact branches, validation evidence, PR titles/bodies, named remote actions | Push stack branches; create draft PRs; edit those drafts  | Ready-for-review, reviewer requests, edits to the original PR, merge |
| D — review (opt-in) | Specific named drafts                                                       | Mark those PRs ready; request reviewers                   | Merge; closing the original PR                                       |

There is no landing gate here: merging the stack (bottom-up, contiguous) is the
human's job after review — `/wrap` refuses native-stack branches today.

## Workflow

### Phase 0 — identify the source and preflight (read-only)

**Identify unambiguously.** Resolve `source` to exactly one of:

- an open PR
  (`gh pr view <n> --json state,isDraft,baseRefName,headRefName,headRefOid,mergeStateStatus`),
- a local branch with commits ahead of the trunk, or
- the current worktree, including uncommitted changes.

Stop and ask when the argument is ambiguous, when the PR is merged, closed, or
queued, or when there is nothing to split (no diff against the trunk).

**Preflight checks**, all read-only:

```bash
git status --porcelain                    # dirty is fine; record it
git rev-parse HEAD                        # pin SOURCE_HEAD
git fetch origin && git rev-parse origin/<trunk>   # pin TRUNK_SHA
git merge-base <TRUNK_SHA> <SOURCE_HEAD>  # pin SOURCE_BASE
gh auth status                            # credentials
git remote -v                             # >1 remote → pass --remote explicitly
gh api "repos/{owner}/{repo}/rules/branches/<trunk>"  # required checks, signed
                                          # commits (best effort)
```

- **In-progress state** — a rebase, merge, cherry-pick, or bisect in the source
  worktree is a stop; finish or abort it first.
- **Existing stack detection** — if the source PR or branch is already part of a
  stack (native `stack` field on the PR, `gh stack view --json` exiting 0, or an
  existing chained-PR arrangement), stop: editing an existing stack is the
  `gh-stack` skill's job, not this one's.
- **Native-stack capability** — detect, never assume, and never install anything
  without explicit approval; see `references/native-stacks.md`. The outcome is
  one of `native` (gh-stack installed and the repo supports stacks), `fallback`
  (plain Git + `gh` chained draft PRs), or `local-only`.
- **Validation commands** — read the repository's AGENTS.md/CLAUDE.md for the
  required check commands and verify they exist before promising per-layer
  validation with them.
- **Suspicious content** — scan the source diff for credentials, unresolved
  conflict markers, or generated files of unknown provenance; stop and surface
  them.

### Phase 1 — plan the layers → Gate A

Analyze the full source diff (`git diff <SOURCE_BASE> <SOURCE_HEAD>` plus
uncommitted changes) and draft an ordered layer manifest: dependencies at the
bottom, dependents above; tests travel with implementation; lockfiles with the
dependency declarations that caused them. Heuristics, the manifest format, and
the per-PR body template live in `references/layer-design.md`. Keep stacks
small: 2–4 layers is the target, 8 the hard cap.

Present the manifest — every layer with branch name, one-sentence intent,
file/hunk assignment, validation plan, and reviewer focus — plus every mutation
the chosen mode implies. **Gate A:** the human approves the plan and the safety
snapshot. If the diff cannot be linearized without artificial coupling, stop and
propose independent PRs instead.

### Phase 2 — snapshot, then replay once onto the trunk → Gate B

1. **Safety snapshot.** Capture the source worktree exactly — without touching
   the user's index, working files, or branch — as a commit on
   `safety/<stack-slug>-source-<timestamp>`, using the temporary-index recipe in
   `references/equivalence-proof.md`. Print the ref and its recovery command
   before continuing. For a clean, fully committed branch the safety ref simply
   pins `SOURCE_HEAD`.
2. **Stack worktree.** Create one worktree for the whole stack as a sibling of
   the main checkout (`<repo>/<stack-slug>/`), following `/create-worktree`
   conventions — env files seeded, dependencies installed — so hooks and
   validation commands actually run.
3. **Reference replay.** From the pinned `TRUNK_SHA`, apply the complete source
   delta once (`git diff --binary <SOURCE_BASE> <SNAPSHOT> | git apply --3way`).
   Any conflict stops the skill for human resolution — no guessing through
   semantic conflicts, migration ordering, lockfiles, or generated artifacts.
   Commit the approved result to `safety/<stack-slug>-reference` and record
   `REFERENCE_SHA`.

**Gate B:** the human approves the conflict resolutions (if any) and the full
reference diff. The reference tree — not the original branch — is now the
contract the stack must reproduce exactly.

### Phase 3 — materialize ordered branches locally

In the stack worktree, starting from `TRUNK_SHA`:

```bash
git switch -c <stack-slug>-01-<layer> "$TRUNK_SHA"
git diff --binary "$TRUNK_SHA" "$REFERENCE_SHA" | git apply
# worktree = reference tree, index = trunk: everything is unstaged residual
# stage layer 1 only, commit, then:
git switch -c <stack-slug>-02-<layer>     # residual carries forward
```

- Stage whole files with `git add <path>`; for a file spanning layers, generate
  the exact patch and `git apply --cached` it — never interactive `git add -p`.
  A hunk that cannot be assigned unambiguously is a stop.
- Commit with `/create-commit` conventions — plain imperative subjects, no type
  prefixes, tests travel with implementation — plus the stack rule: **every
  branch tip must pass required checks on its own**.
- Name layer branches `<stack-slug>-NN-<layer-slug>`, numbered bottom-up.
- In `native` mode, adopt the finished branches locally (no remote change):
  `gh stack init --base <trunk> <branch-01> <branch-02> ...`, then verify with
  `gh stack view --json`.

Full mechanics: `references/equivalence-proof.md`.

### Phase 4 — validate every layer, prove equivalence → Gate C

```bash
git diff --exit-code "$REFERENCE_SHA" "<top-branch>"   # exact end state
git diff --check <parent>..<child>                     # each adjacent pair
git merge-base --is-ancestor <parent> <child>          # strict ancestry
```

Then check out each branch bottom-to-top with a clean tree and run the
repository's required checks per layer. Emit the validation table from
`references/layer-design.md`. Any failure or non-empty equivalence diff → stop,
report, redesign; never publish a broken layer.

**Gate C:** the human approves the exact branches, the evidence, the PR
titles/bodies, and each named remote action (push, draft creation).

### Phase 5 — publish drafts, verify, hand off

Immediately before pushing, run the drift check from
`references/equivalence-proof.md`: fetch again; verify the trunk and the source
remote head have not moved (if the trunk moved: rebase locally, re-run affected
checks, re-prove equivalence, re-approve); verify no target branch name already
exists on the remote.

Publish, in `native` mode:

```bash
gh stack submit --auto --remote origin    # new PRs are created as drafts
gh stack view --json
```

then apply the approved titles/bodies with `gh pr edit`, keeping draft status.
In `fallback` mode, push each branch and open chained draft PRs bottom-up with
`gh pr create --draft --base <parent-branch>` — see
`references/native-stacks.md`.

Verify from GitHub that the PR bases form the exact bottom-to-top chain, checks
triggered on every layer, and the original PR/branch is untouched. Emit the
handoff manifest:

- source/base/trunk/snapshot/reference SHAs and recovery commands;
- the approved layer manifest and branch chain;
- per-layer validation evidence and the equivalence result;
- every remote action performed;
- PR URLs (and `gh stack view --json` output in native mode); and
- the remaining human actions: review bottom-up, mark ready (Gate D), land via a
  stack-aware path — never this skill.

## The original PR

Parallel replacement is the default and the only mode offered unprompted: the
original branch and PR stay exactly as they were, providing rollback and review
history. Only after the human accepts the stack do they decide — separately —
whether to comment on, draft, or close the original.

Reusing the original PR as the stack's top layer (preserve-top cutover) is
opt-in and requires the human to approve force-pushing, retargeting, and review
invalidation explicitly; the conditions under which it must be refused are
listed in `references/native-stacks.md`.

## Stop conditions

Stop, preserve all refs and worktrees, and report when:

- the dependency graph is not linear, or the stack would cross forks or
  repositories;
- native stacks are required but unavailable, and the human declines the
  fallback;
- source, base, or remote heads change after approval;
- the source contains suspected secrets, unresolved conflict markers, or
  sparse-checkout/submodule state the snapshot cannot capture exactly;
- a file or hunk cannot be assigned to a layer unambiguously;
- any layer fails its required checks, or the equivalence diff is non-empty;
- a replay/rebase conflict requires semantic judgment;
- a push updates only some branches, or a force-with-lease is rejected;
- the source PR becomes merged, queued, closed, or edited by someone else
  mid-flight; or
- the next action's mutation class has not been approved.

## Recovery and rollback

- **Before publication:** delete the layer branches and remove the stack
  worktree; the safety snapshot and reference refs stay until the user confirms
  the stack landed. The original worktree was never touched.
- **Restore the source worktree** (if ever needed) from the snapshot:
  `git diff --binary <SOURCE_HEAD> <SNAPSHOT> | git apply` on a clean checkout
  of `SOURCE_HEAD`.
- **After draft publication:** the drafts and branches remain valid Git state.
  Closing the drafts and deleting the remote branches is a named, explicitly
  approved action — never automatic. In native mode, `gh stack unstack` keeps
  PRs and branches, but merged or queued PRs cannot be removed from a stack.
- **Safety refs** are deleted only when the user confirms the stack has fully
  landed.

## Adjacent skills

- **`rewrite-history`** reorganizes one branch's commits; splitting work into
  separately reviewable PRs is this skill's job. Independent work stays
  independent PRs from the trunk: a stack is only for a strictly dependent
  chain.
- **`create-commit`** and **`create-pr`** own commit and PR conventions inside
  each layer. Native-stack PRs go through `gh stack submit --auto` and
  `gh pr edit`, never a standalone `gh pr create`.
- **`wrap`** refuses native-stack branches; landing a stack, bottom-up and
  contiguous, is a human step.
- **`gh-stack`**, the official skill, is the authority for stack command
  semantics, exit codes and recovery when it is installed.

## Examples

**"Split PR #1234 into a stack of standalone PRs I can review one at a time."**

1. Phase 0 resolves PR #1234 to its branch and SHAs, runs preflight, and probes
   native-stack capability.
2. Phase 1 proposes three layers (schema → service → UI) → Gate A.
3. Phases 2–4 snapshot the source, replay it onto `main`, build
   `1234-user-auth-01-schema` … `-03-ui`, validate each layer, and prove the top
   tree equals the reference → Gate C.
4. Phase 5 publishes three draft PRs chained bottom-up; PR #1234 is untouched;
   the handoff manifest lists review order and recovery refs.

**"This worktree got huge — break it into reviewable pieces."** (no PR yet)

Same flow with the dirty worktree as the source: the snapshot captures the
uncommitted work, the reference replay lands it on `origin/main`, and the stack
replaces "one giant future PR" before it ever exists.
