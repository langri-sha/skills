---
name: worktree-reaper
user_invocable: true
description:
  Reclaim disk space in a bare-repo worktree garden. Inventories every worktree,
  reports what each one holds on disk, and removes only those whose branch has
  confidently landed on origin/main — dry run by default, never touching main,
  the bare repo, dirty trees, or worktrees an agent is using. Use when the user
  says "/worktree-reaper", "clean up worktrees", "reap merged worktrees", "the
  garden is full", or wants a periodic disk-space pass over ~/workspace.
metadata:
  author: langri-sha
  version: '1.1.0'
  argument-hint: '[--apply]'
---

# Worktree Reaper

A periodic, disk-space-oriented cleanup pass over a bare-repo worktree garden.
It classifies every worktree, measures what the removable ones hold, and removes
only the ones whose work has demonstrably landed on `origin/main`.

Dry run is the default and the mode meant for periodic use: it reads, measures,
and reports. Removal happens only under `--apply`, and only after a confirmation
typed at the prompt.

`/create-worktree` grows the garden; this skill is what shrinks it.

## Where the Space Actually Goes

Git objects live once in `.bare/` and are shared by every worktree. Removing a
worktree therefore reclaims its **checked-out files only** — `node_modules`,
build output, caches, and other ignored or untracked files. History is never at
stake, and no branch is deleted. That is why a 2 GiB worktree can be removed and
recreated later with `/create-worktree` at the cost of one `pnpm install`.

## Layout It Expects

```
~/workspace/<repo>/          garden root
~/workspace/<repo>/.bare/    bare repository — all objects and refs
~/workspace/<repo>/.git      file: "gitdir: ./.bare"
~/workspace/<repo>/main/     worktree for the primary branch
~/workspace/<repo>/<slug>/   feature worktrees, siblings of main/
```

The reaper validates this layout before doing anything: `.bare/` must be a bare
repository that is a direct child of the garden root, and `.git` must be a
gitdir pointer to it. Anything else is refused outright rather than guessed at.

## Workflow

### 1. Run the Dry Report

From anywhere inside the garden, with the script resolved relative to this
skill's base directory:

```bash
<skill-base-dir>/scripts/reap.sh --fetch
```

`--fetch` refreshes `origin/main` first, which is the only thing the dry run
writes and the only way the landed check sees recent merges. Without it the
report leads with the age of the primary ref so stale verdicts are visible.

### 2. Read the Verdicts

One line per worktree, `reap` first and sorted by size:

```
Worktree reaper — /home/user/workspace/my-app
  primary      origin/main @ b17c2b19 (2026-07-27 02:47, 1d old)
  worktrees    65
  pr evidence  gh pr list on owner/my-app
  in-use scan  25 tmux window(s), process cwds
  mode         dry run

  reap   929-reconcile-cache-state-drift               2.1 GiB  merged via PR #930 (no unique commits, 1 empty commit(s) ignored)
  reap   905-fix-login-bug                             1.8 GiB  merged via PR #906 (patch-equivalent, 3 commit(s) already upstream, 1 empty commit(s) ignored)
  keep   .bare                                               -  bare repository
  keep   main                                                -  primary worktree (main)
  keep   worktree-reaper-skill                               -  current worktree
  skip   pr-693-review                                       -  detached HEAD
  skip   add-search-endpoint                                 -  14 uncommitted or untracked change(s)
  skip   fix-sidebar-layout-shift                            -  not landed on origin/main (38 commit(s) with no upstream equivalent)
  skip   main/.letta/worktrees/1073-wrapup-docs              -  agent-managed nested worktree, not a sibling of main/

  2 reap, 3 keep, 60 skip — 3.9 GiB reclaimable
```

Report the totals and the reap list to the user. If nothing is eligible, say so
along with the dominant skip reasons — that is a useful answer, not a failure.

### 3. Apply, If Asked

```bash
<skill-base-dir>/scripts/reap.sh --fetch --apply
```

Apply re-runs the dry report, then prompts:

```
Remove 2 worktree(s) and reclaim 3.9 GiB? Type y to confirm:
```

Before removing anything, apply re-reads `git worktree list`, re-scans for
activity, and re-runs the **full classifier** on every candidate. A worktree
that went dirty, got a tmux window, gained a process, or stopped being landed
while the report sat on screen is skipped with its fresh reason. The gate that
approves a removal is the same code that produced the report — there is no
second, weaker set of checks to drift out of sync.

Never pipe a confirmation into `--apply` on the user's behalf. The prompt is the
last human gate; a scheduled or looped invocation must stay in dry-run mode.

## What "Landed" Means

PRs land here by rebase-merge, so the branch's commits are rewritten onto `main`
with new SHAs. `git branch --merged` and `merge-base --is-ancestor` match almost
nothing under that workflow and are not used. Instead, per worktree:

`git cherry origin/main <branch>` must report **no unmatched commit that carries
a change** — every commit unique to the branch either has a patch-equivalent
commit already upstream, or alters nothing at all (see Empty Commits).

The evidence is reported per candidate, strongest first:

| Evidence            | Meaning                                                       |
| ------------------- | ------------------------------------------------------------- |
| `merged via PR #n`  | `gh pr list --head <branch> --state merged` found a merged PR |
| `patch-equivalent`  | every unique commit has an upstream twin (the rebase case)    |
| `no unique commits` | the branch adds nothing over `origin/main`                    |

PR evidence is corroboration, not the gate: it strengthens a verdict
`git cherry` already reached, and its absence never makes a branch eligible.
When `gh` is missing or `origin` is not a GitHub remote the header says so and
the run continues offline.

### What Patch-Equivalence Does Not Prove

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

### Empty Commits

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

## Safety Model

Never removed, under any flag:

- the bare repository
- the worktree on the configured `--primary` branch
- the worktree on the repository's default branch, and anything named `main`,
  whatever `--primary` says — a comparison ref is not permission to delete the
  branch everything else is measured against
- the worktree the reaper is invoked from
- anything that is not a direct child of the garden root — nested agent
  worktrees under `.claude/worktrees/`, `main/.letta/worktrees/`, and
  `.bare/.claude/worktrees/` are all excluded by path
- anything whose resolved path leaves the garden root, or that reaches its
  registered location through a symlink

Skipped with a stated reason:

- uncommitted or untracked files (ignored files like `node_modules` do not count
  — they are the point)
- detached HEAD, locked worktrees, unresolvable branch refs
- a worktree HEAD that disagrees with its branch tip
- branches not confidently landed on the primary ref
- worktrees in use: a tmux pane whose `pane_current_path` is inside them, a tmux
  window named exactly the slug, or any process whose cwd is inside them

The header's `in-use scan` line names which of those detections actually ran, so
a run with no tmux server or no `/proc` says so rather than quietly checking
less than you think.

Mechanics:

- removal is `git worktree remove` without `--force`, run from `main/`; a
  refusal from git is treated as a skip, not something to override
- the script never deletes a path itself and never runs a recursive delete
- branches are always kept; the run prints the `git branch -d` commands to run
  by hand if you want them gone
- `git worktree prune` runs only under `--apply`, and only after at least one
  removal succeeded — never as a blanket first step

## Options

| Option             | Effect                                                      |
| ------------------ | ----------------------------------------------------------- |
| `--garden PATH`    | Garden root to operate on (default: derived from cwd)       |
| `--primary REF`    | Remote branch that defines "landed" (default `origin/main`) |
| `--fetch`          | Refresh the primary ref before classifying                  |
| `--all-sizes`      | Measure every worktree, not just reap candidates            |
| `--no-pr-evidence` | Skip the `gh pr list` lookup and stay fully offline         |
| `--strict-commits` | Require an upstream twin for every commit, even empty ones  |
| `--apply`          | Remove candidates after a typed confirmation                |

Exit codes: `0` success, `1` usage or safety refusal, `2` a removal failed.

## Periodic Use

The dry report is cheap — about 4 seconds over 65 worktrees, plus `du` on the
candidates — and mutates nothing, so it is safe to run on a schedule:

```
/loop 1d <skill-base-dir>/scripts/reap.sh --fetch
```

Wire nothing up automatically. Removal stays a human decision each time.

## Edge Cases

- **Branch name differs from the directory name** — reported as
  `<slug> [<branch>]`; classification follows the branch.
- **Several worktrees on one commit** — each is judged on its own branch; the
  shared commit is irrelevant.
- **Stale worktree entries** (directory deleted by hand) — reported as missing
  and left registered until an apply run prunes them.
- **A candidate goes dirty mid-run** — caught by the re-check before removal.
- **Not a bare-repo garden** — the script refuses and explains, rather than
  falling back to guesswork.
- **`du` on a huge garden** — sizes are measured for candidates only; use
  `--all-sizes` when you want the full inventory and can wait.

## Tests

A standalone fixture harness builds a throwaway garden in a temp directory and
covers every classification branch — rebase-merged, patch-equivalent, empty
retrigger commit, unmerged, dirty, untracked, ignored-only, detached, locked,
in-use, nested, out-of-garden, stale, and the protected trio:

```bash
<skill-base-dir>/tests/run-tests.sh
```

It asserts that dry runs change nothing, that apply removes only the landed and
idle worktrees, that branches and the bare repo survive, and that prune runs
only after a successful removal. It never touches a real garden. Run it after
changing `reap.sh`.

## Resources

- **`scripts/reap.sh`** — the reaper: inventory, classification, disk report,
  and the guarded apply path
- **`tests/run-tests.sh`** — fixture harness covering the decision logic
