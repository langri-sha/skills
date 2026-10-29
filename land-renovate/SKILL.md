---
name: land-renovate
user_invocable: true
description: >-
  Batch-land open Renovate PRs in the current repo. Enumerate Renovate-authored
  PRs, classify each as GREEN / CONFLICTING / BEHIND / REAL_FAILURE / HOLD,
  approve and rebase-merge the safe ones in ascending PR-number order, nudge
  conflicting ones with the rebase checkbox, and stop cleanly on real failures
  or cross-file HOLD cases. Use when the user says "/land-renovate", "land the
  Renovate PRs", "clear the Renovate queue", or wants to merge a batch of
  dependency-update PRs.
metadata:
  author: langri-sha
  version: '1.0.0'
  argument-hint: '[limit=N] [<pr-number>...]'
---

# land-renovate

Walk the queue of open Renovate PRs in the current repo and land the safe ones:
enumerate, classify, approve + rebase-merge in ascending PR-number order, nudge
the rest with the rebase checkbox, and stop cleanly on real failures or HOLD
cases.

This operates entirely on existing **remote** PRs through `gh`. It does **not**
call `/create-commit`, `/create-pr`, or `/wrap`, and it does not author local
commits.

## Arguments

| Argument         | Default                        | Description                                        |
| ---------------- | ------------------------------ | -------------------------------------------------- |
| `limit=N`        | `30`                           | Cap how many PRs to walk.                          |
| `<pr-number>...` | all Renovate-authored open PRs | Space-separated PR numbers; operate only on those. |

Defaults: current repo (from `gh repo view --json nameWithOwner`),
Renovate-authored open PRs, ascending PR-number order, no label filter.

## Workflow

### 1. Resolve the repo

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
```

### 2. Enumerate Renovate PRs

List open Renovate-authored PRs, oldest (lowest number) first:

```bash
gh pr list -R "$REPO" --author "app/renovate" --state open --limit 30 \
  --json number,title,headRefOid,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup
```

Sort ascending by `number` and walk them in that order. If explicit PR numbers
were passed as arguments, restrict the set to those.

> **Note:** `gh pr list` often returns `mergeable: UNKNOWN` because GitHub
> computes mergeability lazily. A `gh pr view <n> --json mergeable` on a single
> PR forces the computation. When a PR's `mergeable` is `UNKNOWN`, re-read it
> with `gh pr view` before classifying.

### 3. Classify each PR

Bucket each PR using `statusCheckRollup` + `mergeable` + `mergeStateStatus`:

| Bucket           | Signal                                                                                                                        | Action                                     |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| **GREEN**        | no `FAILURE`/`CANCELLED`/`TIMED_OUT` in rollup, nothing pending, `mergeable=MERGEABLE`, and a ready merge state (below)       | approve + rebase-merge (step 4)            |
| **CONFLICTING**  | `mergeable=CONFLICTING` or `mergeStateStatus=DIRTY`                                                                           | tick the rebase checkbox (step 5), monitor |
| **BEHIND**       | `mergeStateStatus=BEHIND`, or the head lacks the base tip (`behind_by > 0` from `gh api repos/$REPO/compare/<base>...<head>`) | tick the rebase checkbox (step 5), monitor |
| **REAL_FAILURE** | rollup contains a `FAILURE` not auto-fixable by post-upgrade                                                                  | skip; leave for human triage               |
| **HOLD**         | cross-file coordination needed (manual checklist — see below)                                                                 | surface for human; do not proceed          |

A check in the rollup is **pending** when a `CheckRun` has `status != COMPLETED`
or a `StatusContext` has `state` of `PENDING`/`EXPECTED`. It is a **failure**
when a `CheckRun.conclusion` is `FAILURE`/`CANCELLED`/`TIMED_OUT`/
`ACTION_REQUIRED`/`STARTUP_FAILURE`, or a `StatusContext.state` is `FAILURE`/
`ERROR`.

A PR is **behind** once an earlier merge in the batch moves its base: its checks
ran on a tree without that merge, so landing it would ship a combination CI
never tested. Rebasing reruns them on the new base.

The merge state is **ready** when `mergeStateStatus` is `CLEAN` or `HAS_HOOKS`,
or `BLOCKED` only because the PR awaits the approval this skill gives
(`reviewDecision=REVIEW_REQUIRED`). `MERGEABLE` alone means only that the branch
has no conflicts; any other merge state means GitHub would not merge it as is.

#### HOLD checklist (manual — not hard-coded)

HOLD detection is a judgement call the agent makes, not an automated rule. Treat
a PR as a HOLD candidate when landing it in isolation would break something that
lives in another file, for example:

- **terraform-version pin mismatch** — a Terraform provider/CLI bump that needs
  a matching pin updated elsewhere (e.g. `.terraform-version`, CI workflow, or a
  `required_version` constraint) before it is safe.
- **schema bumps requiring code edits** — a dependency upgrade whose new major
  changes a schema/type that hand-written code still depends on; the
  post-upgrade hooks can't generate the code edit.
- any upgrade whose changelog calls for a coordinated edit the post-upgrade job
  won't perform.

When a PR looks like a HOLD, **surface it and ask the user** — do not auto-merge
and do not tick the rebase checkbox. Keep walking the rest of the queue.

### 4. Approve + merge (GREEN)

```bash
gh pr review "$PR" -R "$REPO" --approve \
  --body "LGTM — auto-approved as part of Renovate batch landing."
gh pr view "$PR" -R "$REPO" --json mergeStateStatus -q .mergeStateStatus
```

Merge only when the approval left the merge state `CLEAN` or `HAS_HOOKS`;
anything else goes back to step 3.

```bash
gh pr merge "$PR" -R "$REPO" --rebase --delete-branch --match-head-commit "$HEAD"
```

`$HEAD` is the head SHA the PR was classified at. If Renovate or a bot pushed
since, the merge fails instead of landing commits no check has passed.

### 5. Tick the rebase checkbox (CONFLICTING or BEHIND)

Flip Renovate's rebase checkbox so it rebases the branch, then monitor:

```bash
body=$(gh pr view "$PR" -R "$REPO" --json body -q .body)
new=$(printf '%s' "$body" | sed 's|^\( *\)- \[ \] <!-- rebase-check -->|\1- [x] <!-- rebase-check -->|')
printf '%s' "$new" | gh pr edit "$PR" -R "$REPO" --body-file - >/dev/null
```

Capture the current head SHA as the baseline **before** ticking the box, then
run the monitor (step 6) so you can tell the rebase apart from the state you
started from:

```bash
BASELINE=$(gh pr view "$PR" -R "$REPO" --json headRefOid -q .headRefOid)
```

**Never** tick the rebase checkbox on a REAL_FAILURE — it wastes Renovate cycles
and hides the real problem.

### 6. Monitor until settled

The bundled `scripts/monitor-renovate-pr.sh` polls a single PR until its checks
settle and prints a verdict the agent consumes via the **Monitor** tool.

```bash
scripts/monitor-renovate-pr.sh <pr-number> <repo> <baseline-head-sha-short>
```

- Polls
  `gh pr view --json headRefOid,baseRefName,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup`
  every 45s (`POLL_INTERVAL` override) and prints a line only when the signature
  `${head:0:9}|<mergeable>:<state>|ok=N pend=M fail=K` changes. Once settled, it
  asks the compare API how far the head is behind the base.
- Emits a verdict once the head has moved **off** the baseline, no checks are
  pending, and the signature is stable across two consecutive polls.
- Final stdout line is one of:
  - `GREEN: #<n> ready to merge at <sha>` → go back to step 4 and approve +
    merge at that SHA.
  - `BEHIND: #<n> behind <base> by N commit(s), state=S` → step 5 again.
  - `NOT-GREEN: #<n> settled failures=X mergeable=Y state=Z` → re-classify; it
    is now a REAL_FAILURE or HOLD.
- Optional env: `POLL_INTERVAL` (seconds, default 45), `MAX_POLLS` (give up
  after N polls, `0` = unlimited; on exhaustion emits
  `NOT-GREEN: #<n> timeout ...`).

#### Why a poll loop and not `gh pr checks --watch`

`gh pr checks <n> --watch` is fine for a PR that is already mergeable and just
has checks running, but it actively misleads on the rebase path this skill
exists for:

- **It exits green on the stale head.** Right after the rebase checkbox is
  ticked, the PR's _current_ checks are already terminal — they passed on the
  pre-rebase (conflicting) head. `--watch` sees "no pending checks" and returns
  success **immediately**, before Renovate has even rebased. The
  `head moved off baseline` condition is exactly what guards against that
  false-green.
- **It only knows checks, not mergeability.** The GREEN verdict needs
  `mergeable=MERGEABLE` and a ready `mergeStateStatus`, and CONFLICTING is
  _detected_ via those fields — which `gh pr checks` never reports. A single
  `gh pr view` poll covers both in one shot.
- **The head can move twice**: Renovate's push, then a bot's post-upgrade fix.
  There is a window between them where the known checks are momentarily
  complete; `--watch` can exit in that gap. The "no pending **and** stable for
  two polls" guard rides past it.

## Stopping conditions

- **No GREEN PRs remain** — done.
- **REAL_FAILURE** — skip it, continue with the next PR; never auto-rebase a
  REAL_FAILURE.
- **HOLD candidate** — surface it for a human decision; do not auto-merge.
- **User cancels.**

## Constraints

- **Commit subjects must not contain issue/PR refs** (project rule). Not
  applicable to merging remote PRs here, but if this skill is ever extended to
  author a local commit, keep refs out of the subject — put them in the body.
  See `/create-commit`.
- **Never tick the rebase checkbox on a REAL_FAILURE.**
- **Never auto-merge a HOLD candidate.**
- **HOLD detection is a manual checklist**, not a hard-coded rule. Recognize the
  categories above and surface candidates; don't try to automate the decision.

## Testing notes

### Dry-run classification

Enumerate and eyeball the buckets without touching anything:

```bash
gh pr list -R "$REPO" --author "app/renovate" --state open \
  --json number,title,mergeable,mergeStateStatus,statusCheckRollup \
  | jq -r '.[] | "\(.number)\t\(.mergeable)\t\(.mergeStateStatus)\t\(.title)"'
```

Add a rollup summary per PR to spot pending/failed checks:

```bash
gh pr list -R "$REPO" --author "app/renovate" --state open \
  --json number,statusCheckRollup \
  | jq -r '.[] | "\(.number)\t" + ([.statusCheckRollup[] | .conclusion // .state] | join(","))'
```

### Monitor smoke test

Run the monitor against a known PR with a **fake** baseline SHA (so the head
already counts as "moved") and a short interval to watch the state lines and the
final verdict:

```bash
POLL_INTERVAL=2 MAX_POLLS=4 \
  scripts/monitor-renovate-pr.sh <known-pr> "$REPO" deadbeef0
```

You should see one state line per signature change, then a `GREEN:` /
`NOT-GREEN:` verdict. Passing the PR's **real** head as the baseline instead
exercises the no-rebase path: the head never moves, so it never settles and the
run ends on the `MAX_POLLS` timeout.

## Out of scope

- Hard-coded HOLD detection rules (start as the manual checklist above; extend
  later).
- Wiring this skill into any orchestration layer.
