# Skills

General-purpose agent skills. This repo is their source, so edit them here.
Skills tied to one project live in that project instead.

## Adding skills

Add new general skills here. A skill's `name` frontmatter equals its directory
name; `projen-skills` selects skills by that name.

`babysit-pr` started from openai/codex but is maintained here, so edit it
directly; its `LICENSE.txt`, `NOTICE` and "Modified from openai/codex" lines are
license requirements and stay, even in its test module.

Skills that mirror an upstream project are pinned by `projen-skills` from their
source instead of being copied here.

## Writing skills

The skills serve Claude Code and Codex alike, so they keep to what works on
both.

- **Description:** a third-person verb phrase for what the skill does, then "Use
  when…", then "Not for…" naming the sibling to use instead. Lead with the
  trigger, since both harnesses shorten descriptions once the listing outgrows
  its budget. Leave out angle brackets, which Claude Code shows escaped.
- **Frontmatter:** `name`, `description` and `metadata`, `license` where a skill
  carries its own, plus Claude Code's top-level `argument-hint` and
  `disable-model-invocation` where needed. Keep to these keys.
- **Manual-only skills,** whose side effects should never start unasked, set
  `disable-model-invocation: true` and ship `agents/openai.yaml` with
  `policy.allow_implicit_invocation: false`.
- **Paths:** name bundled files relative to the skill's directory, written
  `<skill-dir>/…` in commands, never `~/.claude/skills/…`.
- **Scripts:** fragile, deterministic mechanics go in `scripts/`; judgment stays
  in prose. Shell variables don't last between an agent's commands, so steps
  pass values literally.
- **Body:** the contract first, since Claude Code keeps only the start of a
  skill after compaction, and within 500 lines. State each rule once, with a
  clause of why only where it would look arbitrary. Design rationale and notes
  for maintainers stay out of SKILL.md.

`test/frontmatter.test.js` checks the rules a test can.

## Repository policy

Never commit on `main`. Work on a branch in its own worktree, a sibling of the
`main/` checkout, and land it through a pull request that merges by rebase. The
repository ruleset keeps `main` linear and refuses force pushes and deletions.

## Releases

Every pull request carries a change file, from `pnpm changeset` or written by
hand:

<!-- prettier-ignore -->
```md
---
"skills": minor
---

Summary
```

Fleet repositories select skills by name, so the bump follows what they notice:

- **major:** a skill is removed or renamed.
- **minor:** a skill is new, or its behavior changes.
- **patch:** wording and fixes.

Dependency and tooling changes that release nothing get an empty change file,
which Renovate pull requests receive automatically.

A release is cut by merging the version pull request that the Release workflow
keeps open: it tags `vX.Y.Z` and creates the GitHub release. Never tag by hand.
