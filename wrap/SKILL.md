---
name: wrap
user_invocable: true
description:
  Land the current branch. Use when the user says "/wrap", "wrap this up", or
  "ship it". Commits remaining changes, rebases, pushes, and merges the PR once
  all checks are green.
---

# Wrap

Commit anything outstanding, rebase, push, and merge the PR once checks are
green. Run it from the feature worktree being landed — never from `main`.

## Steps

1. **Stack guard** — if the `gh-stack` extension is installed
   (`gh extension list`), run `gh stack view --json`. Exit 0 means this branch
   is part of a native GitHub stack: **stop**. Raw rebase/force-push corrupts
   the chain, merging a stacked PR pulls in every unmerged PR below it, and
   native stacks cannot be landed with `gh pr merge` or `--admin` at all.
   Landing a stack is a separate human-driven step (see the `split-pr-stack`
   skill); this skill does not support it yet.

2. **Commit** — if the worktree is dirty, use `/create-commit`. Stop if there
   are unrelated changes that shouldn't be bundled in.

3. **Rebase** — resolve the base branch from the open PR when one exists
   (`gh pr view --json baseRefName -q .baseRefName`), falling back to `main`;
   then fetch and rebase:

   ```bash
   git fetch origin "$BASE_BRANCH"
   git rebase "origin/$BASE_BRANCH"
   ```

   Resolve any conflicts before continuing.

4. **Push** — first push uses `-u`; after a rebase use `--force-with-lease`.

5. **PR** — if no open PR exists, use `/create-pr` (skip the interactive
   confirmation step). If one already exists, leave it as-is.

6. **Watch checks and merge** — wait for all checks to finish:

   ```bash
   gh pr checks <number> --watch
   ```

   **Do not proceed if any check failed or was skipped.** Only run the merge
   when every check reports success:

   ```bash
   gh pr merge <number> --admin --rebase
   ```
