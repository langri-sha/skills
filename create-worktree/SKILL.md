---
name: create-worktree
description: >-
  Creates or reuses a git worktree for a branch, as a sibling of main/ in a
  bare-repo layout, with env files seeded and dependencies installed; hands off
  to worktrunk where the repository configures it. Use when starting work on a
  new branch or switching to one. Not for converting a repository to this layout
  (migrate-git-worktree).
argument-hint: '[slug-or-title]'
metadata:
  author: langri-sha
  version: '2.0.0'
---

# Create Worktree

Create or switch to a git worktree for isolated feature development.

## Path Convention

```
<repo>/                    # Parent directory
<repo>/.bare/              # Bare repository (all objects, refs)
<repo>/.git                # File: "gitdir: ./.bare"
<repo>/main/               # Worktree for main branch
<repo>/<slug>/             # Feature worktree
```

The `.bare/` directory is a bare git repository. The `.git` file at the repo
root is a gitdir pointer. Every branch — including `main` — is a linked
worktree. No branch is special.

## Workflow

### 1. Create or Reuse the Worktree

Without an argument, ask for the feature title first, and turn a title into a
short kebab-case slug.

**With worktrunk.** When the repository has `.config/wt.toml`, let worktrunk
create or reuse the worktree. That file's hooks seed env files and install
dependencies the way the project wants:

```bash
wt switch --create <slug> --no-cd --format json
```

Drop `--create` when the branch already exists. The JSON's `path` is the
worktree. If worktrunk asks to approve the project's hooks, show them to the
user and rerun with `--yes` once they agree.

**Otherwise,** run the bundled script, relative to this skill's directory:

```bash
scripts/create-worktree.sh "<slug-or-title>"
```

It finds the repo root from the bare repository and turns a title into a
kebab-case slug. If `<repo>/<slug>` exists, it reuses it. Otherwise it fetches
origin's default branch, adds the worktree on a new branch (or on the existing
branch of that name), copies `.env.example` files to `.env`, and installs
dependencies with the package manager the lockfile names, reporting a failed
install without failing. The last line of output is the worktree path.

### 2. Then

Report the path, the branch, and whether the worktree was created or reused.
Work from that path with absolute paths: a `cd` doesn't last between commands in
either Claude Code or Codex. In Claude Code, `/rename <slug>` names the session
after the worktree.

If the worktree has `.claude/PLAN.md`, show its progress (tasks done / total)
and offer to continue it with `implementation-plan`.
