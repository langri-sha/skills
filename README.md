# Skills

General-purpose agent skills for Claude Code, Codex and other agents.

## Structure

Each top-level directory is a self-contained skill with a `SKILL.md` entry
point and optional `references/`, `scripts/` and `rules/` directories.

## Usage

Declare the skills a repository uses with [projen-skills], pinned to a commit:

```ts
new Skills(project, {
  skills: [
    {
      source: 'langri-sha/skills',
      ref: '<40-character commit SHA>',
      skills: ['create-commit', 'create-pr'],
    },
  ],
})
```

Or link a skill's directory into the skills directory your agent reads:

```sh
ln -s "$PWD/create-commit" ~/.claude/skills/create-commit
```

Edits made through the link land in this checkout.

## Licensing

MIT, except `babysit-pr`, which is derived from [openai/codex] and stays under
Apache-2.0; its `LICENSE.txt` and `NOTICE` travel with it.

[projen-skills]: https://github.com/langri-sha/projen/tree/main/packages/projen-skills
[openai/codex]: https://github.com/openai/codex
