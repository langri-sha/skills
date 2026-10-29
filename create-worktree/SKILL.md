---
name: create-worktree
description:
  Create or switch to a git worktree for feature development. Creates worktrees
  as sibling directories next to main/ (e.g. <repo>/<slug>). Copies .env.example
  files and runs pnpm install. Use when starting a new feature branch or
  switching between features.
metadata:
  author: langri-sha
  version: '2.0.0'
  argument-hint: '[slug-or-title]'
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

Without an argument, ask for the feature title first. Then run the bundled
script, relative to this skill's directory, with the slug or title:

```bash
scripts/create-worktree.sh "<slug-or-title>"
```

It finds the repo root from the bare repository and turns a title into a
kebab-case slug. If `<repo>/<slug>` exists, it reuses it. Otherwise it fetches
origin's default branch, adds the worktree on a new branch (or on the existing
branch of that name), copies `.env.example` files to `.env`, and runs
`pnpm install`, reporting a failed install without failing. The last line of
output is the worktree path.

### 2. Existing Worktree

When switching to an existing worktree:

1. **Rename the session** to match the slug:

   ```
   /rename <slug>
   ```

2. **Check for existing plan** at `.claude/PLAN.md`

3. **If plan exists**, ask user via AskUserQuestion:
   - "Found existing plan. Resume where you left off?"
   - "Start fresh conversation (plan remains)?"

4. **If resuming**:
   - Read `.claude/PLAN.md` to show progress
   - Read `.claude/memory.md` for context from previous agents
   - Run `/implementation-plan` to continue (it will detect the plan)

5. **Output for existing worktree**:

   ```
   Switched to worktree: <slug>

     Path:   <repo>/<slug>
     Branch: <slug>
     Plan:   Found (.claude/PLAN.md) - 5/12 tasks complete

   Session renamed to: <slug>

   Run /implementation-plan to continue, or start fresh.
   ```

### 3. New Worktree

Rename the Claude session to match the slug for easy identification:

```
/rename <slug>
```

This makes it easy to find and resume this conversation later.

### 4. Output Summary

After creating, display:

```
Worktree created successfully!

  Path:   <repo>/<slug>
  Branch: <slug>
  Source: <repo>/main

Environment files copied:
  - .env
  - apps/web/.env

Dependencies installed via pnpm.

Ready to develop. Run /implementation-plan to create a plan.
```

After switching to existing, display:

```
Switched to worktree: <slug>

  Path:   <repo>/<slug>
  Branch: <slug>

Run 'git status' to see current state.
```

## Quick Reference

```bash
# List all worktrees
git worktree list

# Remove a worktree (from main)
git -C <repo>/main worktree remove <repo>/<slug>

# Prune stale worktree references
git worktree prune

# Delete branch after removing worktree
git branch -d <slug>
```
