# Native stacks, gh-stack, and the fallback path

GitHub-native stacked pull requests are a **public preview** capability
(announced 2026-07-30, staged rollout): a strictly linear chain of PRs in one
repository, each targeting the branch below it, with the bottom PR targeting the
trunk. Verify capability per repository; never assume it.

## What the platform enforces (facts that shape this workflow)

- Every layer is evaluated against the **stack base**: required reviews, status
  checks, CODEOWNERS, and rulesets come from the trunk, and CI runs once per PR
  as though it targeted the trunk. Stack metadata is exposed at
  `github.event.pull_request.stack` (`number`, `size`, `position`, `base.ref`,
  `base.sha`) for optimizing expensive steps.
- Stacks land **bottom-up**: the lowest unmerged PR alone, or a contiguous
  prefix — all-or-nothing. A mid-stack PR cannot merge in isolation.
- **No auto-merge, no admin bypass.** `gh pr merge` and the legacy synchronous
  merge REST endpoint cannot land a stacked PR at all; programmatic merging uses
  a dedicated asynchronous endpoint.
- Closing a middle PR blocks everything above it until the chain is repaired.
- The server-side "Rebase stack" button force-pushes **unsigned** commits;
  repositories requiring signed commits must rebase locally (`gh stack rebase`)
  and push (`gh stack push`).
- Cross-fork and DAG-shaped stacks are unsupported. GitHub Desktop is
  unsupported; do not depend on Mobile for construction or recovery.

## Capability detection (read-only, in order)

```bash
gh --version                                  # gh 2.0+ required for the extension
gh auth status
gh extension list | grep -F 'github/gh-stack' # installed?
gh stack view --json; echo "exit: $?"         # in-repo probe
```

Interpret `gh stack view --json` by exit code: `0` — the current branch is
already in a stack (stop: that is the `gh-stack` skill's territory), `2` —
stacks work here, the current branch just is not in one (the good outcome), `9`
— stacked PRs are unavailable on this repository. Other codes: consult the
official `gh-stack` skill.

Decide the mode:

| Outcome                                      | Mode                                 |
| -------------------------------------------- | ------------------------------------ |
| Extension installed, probe exit ≠ 9          | `native`                             |
| Extension missing or probe exit = 9          | `fallback` (or offer install, below) |
| No push access, or user declines remote work | `local-only`                         |

**Never install `github/gh-stack` unilaterally.** Offer it, name the exact
command (`gh extension install github/gh-stack`), and proceed only on explicit
approval — pinning or verifying the version. Declining is fine: the fallback
path publishes the same branch chain.

## Operating gh-stack from this skill (native mode)

The official `gh-stack` skill, when installed, is the authority on command
semantics, exit codes, and recovery. The subset this workflow relies on:

- Always the non-interactive forms: `gh stack view --json`,
  `gh stack init --base <trunk> <branches...>`, `gh stack submit --auto`,
  `gh stack rebase`, `gh stack push`, `gh stack sync`. Never `modify`, `switch`,
  or any bare command that opens a prompt or a TUI.
- With more than one remote, pass `--remote <name>` explicitly (or require
  `remote.pushDefault` to be configured).
- `gh stack init` with explicit branch arguments **adopts existing local
  branches without touching the remote** — which is why materialization can
  finish before any approval to push.
- `gh stack submit --auto` pushes the branches and creates missing PRs **as
  drafts**; titles and bodies are auto-generated, so apply the approved ones
  with `gh pr edit` afterwards, keeping draft status.
- `gh stack push` force-with-leases each branch but is **not atomic** across
  branches: some branches can update while another lease is rejected. Treat a
  partial push as a stop condition and reconcile before anything else.
- `gh stack sync` can detect divergence, change nothing, print `Sync aborted`,
  and still **exit 0**. Compare `view --json` before and after; never trust the
  exit code alone.
- There is no non-interactive reorder or removal: restructuring after
  publication means `unstack` then `init` again, each with approval.

## Post-publication verification (native mode)

```bash
gh stack view --json
gh api "repos/{owner}/{repo}/pulls/<n>" \
  -H "X-GitHub-Api-Version: 2026-03-10" --jq '.stack'
```

Confirm: the bases form the exact bottom-to-top chain; all PRs belong to one
stack whose base, size, positions, branches, and head SHAs match the manifest;
every PR is a draft; checks triggered on every layer; the original PR and branch
are untouched.

## Fallback: plain Git + `gh` chained drafts

When native stacks or `gh-stack` are unavailable, or the user prefers not to
install anything, publish the same branch chain as classic stacked PRs:

```bash
# after Gate C, bottom-up
git push -u origin <stack-slug>-01-<layer>
gh pr create --draft --base <trunk> --head <stack-slug>-01-<layer> ...
git push -u origin <stack-slug>-02-<layer>
gh pr create --draft --base <stack-slug>-01-<layer> \
  --head <stack-slug>-02-<layer> ...
```

Each PR still shows only its own layer's diff. Known differences from native
mode — state them in the handoff:

- No stack map, no stack metadata in CI, no `gh stack` navigation or cascading
  rebase; rules and required checks apply per PR against its (branch) base.
- Landing is per-PR, bottom-up, by the human. After a lower PR merges and its
  head branch is deleted, GitHub retargets dependent PRs onto that branch's own
  base (long-standing behavior — verify after each landing); the local branches
  above still need a manual cascade (`git rebase --onto`, then
  `git push --force-with-lease` per branch — each cascade is an approved
  action).
- The PR bodies must carry the position and review order, since GitHub renders
  no map for the chain.

The chain can be adopted into a native stack later — `gh stack link`, or the web
UI, can recognize chained PRs — as a separate, explicitly approved step. Note
that `link` does not create local `gh-stack` tracking; keep one local manager as
the source of truth.

## Preserve-top cutover (opt-in only)

The default remains parallel replacement. Reusing the original PR as the stack's
top layer requires the human to approve **all** of:

- force-with-lease updating its head branch;
- retargeting its base onto the layer below;
- the likely dismissal/invalidation of existing approvals and stale comments;
- fresh CI runs; and
- linking it into the stack.

Refuse preserve-top entirely when the PR is queued, a merge is in progress,
another author is pushing to it, its remote head changed after inspection, or
branch policy forbids rewriting it.
