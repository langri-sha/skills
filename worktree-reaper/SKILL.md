---
name: worktree-reaper
user_invocable: true
description:
  Reclaim disk space in a bare-repo worktree garden. Inventories every worktree,
  reports what each one holds on disk, and removes only those whose branch has
  confidently landed on origin/main — dry run by default, never touching main,
  the bare repo, dirty trees, or worktrees an agent is using. Use when the user
  says "/worktree-reaper", "clean up worktrees", "reap merged worktrees", "the
  garden is full", or wants a periodic disk-space pass over their worktrees.
metadata:
  author: langri-sha
  version: '1.2.0'
  argument-hint: '[--apply]'
---

# Worktree Reaper

A periodic, disk-space-oriented cleanup pass over a bare-repo worktree garden.
It classifies every worktree, measures what the removable ones hold, and removes
only the ones whose work has demonstrably landed on `origin/main`.

Dry run is the default and the mode meant for periodic use: it reads, measures,
and reports. Removal happens only under `--apply`, and only after a confirmation
typed at the prompt.

Git objects live once in `.bare/`, so removing a worktree reclaims only its
checked-out files: `node_modules`, build output, caches. `/create-worktree`
grows the garden; this skill is what shrinks it.

## Layout It Expects

```
<repo>/          garden root
<repo>/.bare/    bare repository — all objects and refs
<repo>/.git      file: "gitdir: ./.bare"
<repo>/main/     worktree for the primary branch
<repo>/<slug>/   feature worktrees, siblings of main/
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
Worktree reaper — /home/user/src/my-app
  primary      origin/main @ b17c2b19 (2026-07-27 02:47, 1d old)
  worktrees    65
  pr evidence  gh pr list on owner/my-app
  in-use scan  25 tmux window(s), 9 herdr tab(s), process cwds
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
that went dirty, got a tmux window or Herdr tab, gained a process, or stopped
being landed while the report sat on screen is skipped with its fresh reason.

Never pipe a confirmation into `--apply` on the user's behalf. The prompt is the
last human gate; a scheduled or looped invocation must stay in dry-run mode.

## What "Landed" Means

PRs land here by rebase-merge, so the branch's commits are rewritten onto `main`
with new SHAs. `git branch --merged` and `merge-base --is-ancestor` match almost
nothing under that workflow and are not used. Instead, per worktree:

`git cherry origin/main <branch>` must report **no unmatched commit that carries
a change** — every commit unique to the branch either has a patch-equivalent
commit already upstream, or alters nothing at all (see below).

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

`git cherry` proves the commits appear in the primary's history, not that its
current tree still holds them: a change that landed and was later reverted still
reads as landed. Removal keeps the branch, so `git worktree add <path> <branch>`
brings the worktree back.

A commit that changes no files, such as `Retrigger CI`, has no patch for
`git cherry` to match, and rebase-merge drops it, so it would hold its branch
back forever. It cannot carry unlanded work, so it doesn't count; candidates say
so in their evidence (`1 empty commit(s) ignored`). `--strict-commits` restores
the commit-for-commit rule, which keeps any branch that ever needed a CI
retrigger.

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
  window named exactly the slug, a Herdr pane whose `cwd` is inside them, a
  Herdr tab or workspace labelled exactly the slug, or any process whose cwd is
  inside them

The header's `in-use scan` line names which of those detections actually ran, so
a run with no tmux, no Herdr server, or no `/proc` says so rather than quietly
checking less than you think. Each multiplexer scan reaches one server: tmux's
from `$TMUX` or its default socket, Herdr's from `HERDR_SOCKET_PATH` or its
default session. Herdr clears `TMUX` in its panes, so a run inside Herdr nested
in tmux sees the outer tmux only when that runs on the default socket.

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

The dry report mutates nothing, so it is safe to run on a schedule. Wire nothing
up automatically: removal stays a human decision each time.

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

## Resources

- **`scripts/reap.sh`** — the reaper: inventory, classification, disk report,
  and the guarded apply path
- **[`references/design.md`](references/design.md)** — why it works this way:
  where the space goes, what patch-equivalence misses, empty commits, and the
  fixture tests
