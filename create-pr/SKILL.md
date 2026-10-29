---
name: create-pr
description: >-
  Opens a GitHub pull request for the current branch with gh: picks the base,
  fills the repo's PR template in under 150 words, and refuses branches that
  belong to a native GitHub stack. Use when asked to create, open or update a
  PR. Not for splitting a change into a stack (split-pr-stack) or merging
  (wrap).
---

# Create PR

## Before writing anything

- **Native stack guard.** If `gh extension list` shows `gh-stack`, run
  `gh stack view --json`. Exit 0 means this branch is in a native stack: open no
  standalone PR, even when the user names a base; surface the conflict instead.
  Publish with `gh stack submit --auto`, which opens drafts, then set each
  layer's title and body with `gh pr edit`. The `split-pr-stack` skill builds
  such stacks.
- **Base.** The user's, if named. Otherwise, if the branch sits on another open
  PR's branch, base on that branch so the PR shows only this layer: after
  `git fetch origin`, test each `headRefName` from
  `gh pr list --json headRefName` with
  `git merge-base --is-ancestor origin/<head> HEAD`, take the nearest, and ask
  when more than one fits. Otherwise the default branch
  (`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`).
- **Existing PR.** `gh pr list --head <branch> --json url`. If one exists, offer
  `gh pr edit` instead of opening a duplicate.
- **State.** Uncommitted changes won't be in the PR, so ask whether to commit
  them (`create-commit`), stash them, or leave them out. On a detached HEAD,
  create a short kebab-case branch named for the change, with no type prefix. An
  empty diff against `origin/<base>` means there is nothing to open; say so. If
  the branch is behind `origin/<base>`, suggest rebasing before pushing.

Compare against the remote base, since local refs go stale:
`git fetch origin <base>`, then `git log origin/<base>..HEAD` and
`git diff origin/<base>...HEAD`.

## Title

A plain sentence in sentence case, starting with an imperative verb, with no
trailing period. Describe what the change does; the branch name and commit
subjects are input, not output. Use a title the user gives verbatim. Drop type
prefixes (`feat:`, `fix(api):`) and markers like `[WIP]`, and keep acronyms
upper case. Mirror the issue title when the PR resolves one and it already reads
plainly. Backtick a package or symbol only when it helps: "Bump `eslint` to v9".

## Body

The whole body stays under 150 words, whatever the template asks for. Reviewers
skim, and the diff and commits already say what changed.

- Use the repo's template (`.github/pull_request_template.md` or a variant).
  Fill only its sections, skip any with nothing to say rather than writing N/A,
  add none of your own, and leave checkboxes unchecked.
- Summary: why the change exists, plus what the diff can't show, such as manual
  steps, risk or rollout. One to three sentences. Fold in anything the user
  asked to mention.
- Don't list the changes. Spend one sentence only on a decision a reviewer would
  otherwise miss.
- Test plan: one line naming what ran.
- Write as the author, in the first person or with no attribution. Never name
  the author or refer to them in the third person.
- `Closes #123` when the branch resolves an issue.
- In a stack, describe this layer only. GitHub renders the stack, so add no
  stack section, PR list or "builds on #123".

Without a template, write a short paragraph and the one-line test plan, with no
headings.

## Open it

Show the title and body and ask for a go, unless the user asked for a
non-interactive run or a composing skill such as `wrap` said to skip it:

```bash
git push -u origin <branch>
gh pr create --base <base> --title "<title>" --body-file <file>
```

Add `--label` for the kind of change (`bug`, `enhancement`, `documentation`,
`dependencies`) only when `gh label list --limit 1000` shows it: `gh pr create`
refuses a label the repository doesn't have. Request reviewers only when the
user names them or CODEOWNERS clearly applies. Return the PR URL.
