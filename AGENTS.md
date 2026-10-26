# Skills

General-purpose agent skills. This repo is their source, so edit them here.
Skills tied to one project live in that project instead.

## Adding skills

Add new general skills here and push. A skill's `name` frontmatter equals its
directory name; `projen-skills` selects skills by that name.

`babysit-pr` started from openai/codex but is maintained here, so edit it
directly; its `LICENSE.txt`, `NOTICE` and "Modified from openai/codex" lines are
license requirements and stay, even in its test module.

Skills that mirror an upstream project are pinned by `projen-skills` from their
source instead of being copied here.

## Repository policy

Commit on `main` and push each commit immediately, without asking. The
repository ruleset refuses force pushes and deletions.
