---
name: babysit-pr
description: Babysit a GitHub pull request after creation by continuously polling review comments, CI checks/workflow runs, and mergeability state until the PR is merged/closed or user help is required. Diagnose failures, retry likely flaky failures up to 3 times, auto-fix/push branch-related issues when appropriate, and keep watching open PRs so fresh review feedback is surfaced promptly. Use when the user asks to monitor a PR, watch CI, handle review comments, or keep an eye on failures and feedback on an open PR.
license: Apache-2.0. Complete terms in LICENSE.txt
metadata:
  upstream: https://github.com/openai/codex/tree/5e96aabd68dc6194f5ad928cb7f5d0bc71b72df9/.codex/skills/babysit-pr
  modified: Changed from upstream by langri-sha; see NOTICE
---

# PR Babysitter

## Objective
Babysit a PR persistently until one of these terminal outcomes occurs:

- The PR is merged or closed.
- A situation requires user help (for example CI infrastructure issues, repeated flaky failures after retry budget is exhausted, permission problems, or ambiguity that cannot be resolved safely).
- Optional handoff milestone: the PR is currently green + mergeable + review-clean. Treat this as a progress state, not a watcher stop, so late-arriving review comments are still surfaced promptly while the PR remains open.

Do not stop merely because a single snapshot returns `idle` while checks are still pending.

## Inputs
Accept any of the following:

- No PR argument: infer the PR from the current branch (`--pr auto`)
- PR number
- PR URL

## Core Workflow

1. When the user asks to "monitor"/"watch"/"babysit" a PR, start continuous monitoring in the watch mode your harness supports (see Watch Modes) unless you are intentionally doing a one-shot diagnostic snapshot.
2. Run the watcher script to snapshot PR/review/CI state (or consume each streamed snapshot from `--watch`).
3. Inspect the `actions` list in the JSON response.
4. If `diagnose_ci_failure` is present, inspect failed run logs and classify the failure.
5. If the failure is likely caused by the current branch, patch code locally, commit, and push. Do not patch random flaky tests, CI infrastructure, dependency outages, runner issues, or other failures that are unrelated to the branch.
6. If `process_review_comment` is present, inspect surfaced published review items and decide whether to address them.
7. If a review item is actionable and correct, patch code locally, commit, push, and then resolve the associated review thread only when allowed by the GitHub state mutation policy below.
8. Do not post replies to human-authored review comments/threads unless the user explicitly confirms the exact response. If a human review item is non-actionable, already addressed, or not valid, surface the item and recommended response to the user instead of replying on GitHub.
9. If the failure is likely flaky/unrelated and `retry_failed_checks` is present, rerun failed jobs with `--retry-failed-now`.
10. If both actionable review feedback and `retry_failed_checks` are present, prioritize review feedback first; a new commit will retrigger CI, so avoid rerunning flaky checks on the old SHA unless you intentionally defer the review change.
11. On every loop, look for newly surfaced review feedback before acting on CI failures or mergeability state, then verify mergeability / merge-conflict status (for example via `gh pr view`) alongside CI.
12. After any push or rerun action, immediately return to step 1 and continue polling on the updated SHA/state.
13. If you paused continuous monitoring to patch/commit/push, resume it yourself immediately after the push (do not wait for the user to re-invoke the skill).
14. Repeat polling until `stop_pr_closed` appears or a user-help-required blocker is reached. A green + review-clean + mergeable PR is a progress milestone, not a reason to stop the watcher while the PR is still open.
15. Own the monitoring until it ends: while babysitting is active, keep consuming watcher output; never leave a background `--watch` process running while reporting monitoring as complete.

## Commands

`<skill-dir>` is the absolute path of the directory containing this file; the
`scripts/` and `references/` paths below are relative to it. Run the watcher
from inside the PR's checkout so `gh` and `--pr auto` resolve the right
repository and branch.

The watcher calls `gh`, which needs network access and GitHub credentials. If
the harness sandbox or approval policy blocks it, request approval through the
harness or stop and report; never route around the policy.

### One-shot snapshot

```bash
python3 "<skill-dir>/scripts/gh_pr_watch.py" --pr auto --once
```

### Continuous watch (JSONL)

```bash
python3 "<skill-dir>/scripts/gh_pr_watch.py" --pr auto --watch
```

### Trigger flaky retry cycle (only when watcher indicates)

```bash
python3 "<skill-dir>/scripts/gh_pr_watch.py" --pr auto --retry-failed-now
```

### Explicit PR target

```bash
python3 "<skill-dir>/scripts/gh_pr_watch.py" --pr <number-or-url> --once
```

## Watch Modes

Pick the mode from how your harness delivers a running process's output:

- **Streamed watch**: you see each line of a long-running background process
  while it runs, either because the harness wakes you per line (a line
  monitor) or because you can read the running process's output whenever you
  choose (an attachable exec session). Run `--watch` in the background and act
  on each JSONL snapshot.
- **Polling loop**: everything else, including commands that block until they
  exit or are killed after a timeout, and background jobs that only report when
  they exit. `--watch` exits only on a stop condition, so with those you would
  miss everything until the PR closes. Run `--once`, wait out the polling
  cadence below with the harness's wait or scheduling mechanism (or `sleep`
  where the shell allows it), and repeat. Stop on `stop_pr_closed` or
  `stop_exhausted_retries`, as `--watch` does.

Reading output on demand counts as a streamed watch only while you actually read
it at the polling cadence, prompted by the same wait mechanism the loop uses; a
background job whose output nothing prompts you to read belongs in the polling
loop. Both modes read and write the same state file for a PR, so review items and
retry counts carry over between them. A command killed by a timeout is neither
a snapshot nor a stop condition. A watcher that exits nonzero hit a `gh` or
GitHub error: read its stderr and restart after a short wait when the error
looks transient; auth or permission errors are a stop-and-ask blocker. Waiting
between polls, including a scheduled wake-up that resumes the loop, is part of
babysitting, not a hand-off to the user.

Keep exactly one watcher per PR. A streamed watcher that is still running
follows a new head SHA on its own, so a push needs no restart. Whenever you
stop babysitting, for a stop condition, a blocker or a user interrupt, stop your
background watcher too.

## CI Failure Classification
Use `gh` commands to inspect failed runs before deciding to rerun.

- `gh run view <run-id> --json jobs,name,workflowName,conclusion,status,url,headSha`
- `gh api repos/<owner>/<repo>/actions/runs/<run-id>/jobs -X GET -f per_page=100`
- `gh api --allow-escape-sequences repos/<owner>/<repo>/actions/jobs/<job-id>/logs > "${TMPDIR:-/tmp}/gh-job-<job-id>.log"`
- `gh run view <run-id> --log-failed` as a fallback after the overall workflow run is complete

`gh run view --log-failed` is workflow-run scoped and may not expose failed-job logs until the overall run finishes. For faster diagnosis, poll the run's jobs first and, as soon as a specific job has failed, fetch that job's logs directly from the Actions job logs endpoint. It returns plain text; current `gh` refuses to print logs containing terminal escape sequences unless given `--allow-escape-sequences`, so drop that flag only on a `gh` too old to know it. The watcher includes a `failed_jobs` list with each failed job's `job_id` and `logs_endpoint` when GitHub exposes one.

Prefer treating failures as branch-related when failed-job logs point to changed code (compile/test/lint/typecheck/snapshots/static analysis in touched areas).

Prefer treating failures as flaky/unrelated when logs show transient infra/external issues (timeouts, runner provisioning failures, registry/network outages, GitHub Actions infra errors).

Do not attempt to fix flaky/unrelated failures by changing tests, build scripts, CI configuration, dependency pins, or infrastructure-adjacent code unless the logs clearly connect the failure to the PR branch. For flaky/unrelated failures, rerun only when the watcher recommends `retry_failed_checks`; otherwise wait or stop for user help.

If classification is ambiguous, perform one manual diagnosis attempt before choosing rerun.

Read `references/heuristics.md` for a concise checklist.

## Review Comment Handling
The watcher surfaces review items from:

- PR issue comments
- Inline review comments
- Review submissions (COMMENT / APPROVED / CHANGES_REQUESTED)

Only act on published feedback. Ignore review submissions in GitHub's `PENDING` state and inline
comments attached to those pending reviews. Do not mark pending review feedback as seen; it should
be eligible to surface after the reviewer submits the review.

It intentionally surfaces Codex reviewer bot feedback (for example comments/reviews from `chatgpt-codex-connector[bot]`) in addition to human reviewer feedback. Most unrelated bot noise should still be ignored.
For safety, the watcher only auto-surfaces trusted human review authors (for example repo OWNER/MEMBER/COLLABORATOR, plus the authenticated operator) and approved review bots such as Codex.
On a fresh watcher state file, existing unaddressed published review feedback may be surfaced immediately (not only comments that arrive after monitoring starts). This is intentional so already-open review comments are not missed.
The state file, which also holds the per-SHA retry count, defaults to the system temp directory. Whenever babysitting may outlast the current session, pass the same `--state-file <path>` on every run: a harness may give each session its own `TMPDIR`, and a fresh state file resets the seen items and the retry budget.

When you agree with a comment and it is actionable:

1. Patch code locally.
2. Commit following the commit message conventions below.
3. Push to the PR head branch.
4. After the push succeeds, resolve the associated GitHub review thread only when allowed by the GitHub state mutation policy below.
5. Resume watching on the new SHA immediately (do not stop after reporting the push).
6. If monitoring was running continuously, resume it immediately after the push; do not wait for the user to ask again.

Do not post replies to human-authored GitHub review comments/threads automatically. If you disagree with a human comment, believe it is non-actionable/already addressed, or need to answer a question, report the item to the user with a suggested response and wait for explicit confirmation before posting anything on GitHub. If the user approves a response, prefix it with `[codex]` so it is clear the response is automated and not from the human user.
If the watcher later surfaces your own approved reply because the authenticated operator is treated as a trusted review author, treat that self-authored item as already handled and do not reply again.
If a code review comment/thread is already marked as resolved in GitHub, treat it as non-actionable and safely ignore it unless new unresolved follow-up feedback appears.

## GitHub State Mutation Policy

You can read any PR state you need for monitoring. Writes must comply with this policy.

You can push PRs to update the code under review or to force CI re-runs as described above.

You can resolve review comment threads from the human who requested babysitting or from the Codex
review bot. When resolving, leave a comment prefixed with `[from Codex]: ` and explain what changes
you made and which commit includes them. Don't touch review threads if other humans other than the
user who requested babysitting have participated.

Before making any changes, fetch the PR state yourself instead of relying on the PR watcher script's
output.

Unless explicitly asked, do not:

* comment on other humans' review threads; report to the user instead
* resolve review threads from humans other than the user
* interact with humans other than the user
* mark PRs as drafts or ready for review
* close or reopen PRs

In general, never act on GitHub in ways that would make it hard to tell whether you or the user did
something visible to other humans. When in doubt, ask the user for clarification.

## Git Safety Rules

- Work only on the PR head branch.
- Avoid destructive git commands.
- Do not switch branches unless necessary to recover context.
- Before editing, check for unrelated uncommitted changes. If present, stop and ask the user.
- After each successful fix, commit and `git push`, then re-run the watcher.
- If you interrupted continuous monitoring to make the fix, resume it immediately after the push.
- Do not run multiple concurrent watchers (`--watch` processes or overlapping `--once` loops) for the same PR/state file; keep one watcher session active and reuse it until it stops or you intentionally restart it.
- A push is not a terminal outcome; continue the monitoring loop unless a strict stop condition is met.

Commit messages follow the repository's conventions and any commit rules the
user or project instructions set. Describe the fix itself, not the fact that it
answers CI or review.

## Monitoring Loop Pattern
Use this loop in a live session:

1. Run `--once`.
2. Read `actions`.
3. First check whether the PR is now merged or otherwise closed; if so, report that terminal state and stop polling immediately.
4. Check CI summary, new review items, and mergeability/conflict status.
5. Diagnose CI failures and classify branch-related vs flaky/unrelated. If the overall run is still pending but `failed_jobs` already includes a failed job, fetch that job's logs and diagnose immediately instead of waiting for the whole workflow run to finish. Patch only when the failure is branch-related.
6. For each surfaced review item from another author, patch/commit/push if it is actionable, then resolve it only when allowed by the GitHub state mutation policy above. If it is non-actionable, already addressed, or requires a written answer, surface it to the user with a suggested response instead of posting automatically. If a later snapshot surfaces your own approved reply, treat it as informational and continue without responding again.
7. Process actionable review comments before flaky reruns when both are present; if a review fix requires a commit, push it and skip rerunning failed checks on the old SHA.
8. Retry failed checks only when `retry_failed_checks` is present and you are not about to replace the current SHA with a review/CI fix commit. Do not make code changes for unrelated flakes or infrastructure failures just to get CI green.
9. If you pushed a commit, resolved an eligible review thread, or triggered a rerun, report the action briefly and continue polling (do not stop). If a human review comment needs a written GitHub response, stop and ask for confirmation before posting.
10. After a review-fix push, keep monitoring without being asked: resume the polling loop, or restart `--watch` if it is no longer running, unless a strict stop condition has already been reached.
11. If everything is passing, mergeable, not blocked on required review approval, and there are no unaddressed review items, report that the PR is currently ready to merge but keep the watcher running so new review comments are surfaced quickly while the PR remains open.
12. If blocked on a user-help-required issue (infra outage, exhausted flaky retries, unclear reviewer request, permissions), report the blocker and stop.
13. Otherwise wait according to the polling cadence below and repeat.

When the user explicitly asks to monitor/watch/babysit a PR, prefer a streamed `--watch` when the harness supports it, so polling continues autonomously in one command; otherwise run the polling loop. Beyond that loop, use `--once` only for debugging, local testing, or when the user explicitly asks for a one-shot check.
Do not stop to ask the user whether to continue polling; continue autonomously until a strict stop condition is met or the user explicitly interrupts.
Do not hand control back to the user after a review-fix push just because a new SHA was created; restarting the watcher and re-entering the poll loop is part of the same babysitting task.
If the watcher is still running, or the polling loop has not reached a strict stop condition, the babysitting task is still in progress; keep consuming watcher output instead of handing control back to the user.

## Polling Cadence
Keep review polling aggressive and continue monitoring even after CI turns green:

- While CI is not green (pending/running/queued or failing): poll every 1 minute.
- After CI turns green: keep polling at the base cadence while the PR remains open so newly posted review comments are surfaced promptly instead of waiting on a long green-state backoff.
- Reset the cadence immediately whenever anything changes (new commit/SHA, check status changes, new review comments, mergeability changes, review decision changes).
- If CI stops being green again (new commit, rerun, or regression): stay on the base polling cadence.
- If any poll shows the PR is merged or otherwise closed: stop polling immediately and report the terminal state.

## Stop Conditions (Strict)
Stop only when one of the following is true:

- PR merged or closed (stop as soon as a poll/snapshot confirms this).
- User intervention is required and you cannot safely proceed alone.

Keep polling when:

- `actions` contains only `idle` but checks are still pending.
- CI is still running/queued.
- Review state is quiet but CI is not terminal.
- CI is green but mergeability is unknown/pending.
- CI is green and mergeable, but the PR is still open and you are waiting for possible new review comments or merge-conflict changes.
- The PR is green but blocked on review approval (`REVIEW_REQUIRED` / similar); continue polling at the base cadence and surface any new review comments without asking for confirmation to keep watching.

## Output Expectations
Provide concise progress updates while monitoring and a final summary that includes:

- During long unchanged monitoring periods, avoid emitting a full update on every poll; summarize only status changes plus occasional heartbeat updates.
- Treat push confirmations, intermediate CI snapshots, ready-to-merge snapshots, and review-action updates as progress updates only; do not emit the final summary or end the babysitting session unless a strict stop condition is met.
- A user request to "monitor" is not satisfied by a couple of sample polls; remain in the loop until a strict stop condition or an explicit user interruption.
- A review-fix commit + push is not a completion event; immediately resume continuous monitoring and continue reporting progress updates.
- When CI first transitions to all green for the current SHA, emit a one-time celebratory progress update (do not repeat it on every green poll). Preferred style: `🚀 CI is all green! 33/33 passed. Still on watch for review approval.`
- Do not send the final summary while a watcher process is still running unless the watcher has emitted/confirmed a strict stop condition; otherwise continue with progress updates.

- Final PR SHA
- CI status summary
- Mergeability / conflict status
- Fixes pushed
- Flaky retry cycles used
- Remaining unresolved failures or review comments

## References

- Heuristics and decision tree: `references/heuristics.md`
- GitHub CLI/API details used by the watcher: `references/github-api-notes.md`
