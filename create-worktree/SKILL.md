---
name: create-worktree
description:
  Create or switch to a git worktree for feature development. Creates worktrees
  as sibling directories next to main/ (e.g. ~/workspace/<repo>/<slug>). Copies
  .env.example files and runs pnpm install. Use when starting a new feature
  branch or switching between features.
metadata:
  author: langri-sha
  version: '2.0.0'
  argument-hint: '[slug-or-title]'
---

# Create Worktree

Create or switch to a git worktree for isolated feature development.

## Path Convention

```
~/workspace/<repo>/                    # Parent directory
~/workspace/<repo>/.bare/              # Bare repository (all objects, refs)
~/workspace/<repo>/.git                # File: "gitdir: ./.bare"
~/workspace/<repo>/main/               # Worktree for main branch
~/workspace/<repo>/<slug>/             # Feature worktree
```

The `.bare/` directory is a bare git repository. The `.git` file at the repo
root is a gitdir pointer. Every branch — including `main` — is a linked
worktree. No branch is special.

## Workflow

### 1. Detect Source Repository

Use `git worktree list` to find the main worktree (always first entry):

```bash
# Get the main worktree path (works from any worktree)
MAIN_PATH=$(git worktree list | head -1 | awk '{print $1}')
REPO_ROOT=$(dirname "$MAIN_PATH")

echo "Main worktree: $MAIN_PATH"
echo "Repo root: $REPO_ROOT"
```

Example:

- Running from: `~/workspace/my-app/add-login/`
- Detects main: `~/workspace/my-app/main/`
- Repo root: `~/workspace/my-app/`

### 2. If Argument Provided - Check for Existing Worktree

If the user provides an argument, first check if it matches an existing
worktree:

```bash
SLUG="$1"

# Check if worktree exists
if [ -d "$REPO_ROOT/$SLUG" ]; then
  cd "$REPO_ROOT/$SLUG"
  echo "Switched to existing worktree: $SLUG"
  pwd
fi

# If not found as slug, treat argument as title and create new worktree
TITLE="$1"
```

#### 2.1 For Existing Worktree - Rename Session and Check for Plan

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

     Path:   ~/workspace/<repo>/<slug>
     Branch: <slug>
     Plan:   Found (.claude/PLAN.md) - 5/12 tasks complete

   Session renamed to: <slug>

   Run /implementation-plan to continue, or start fresh.
   ```

### 3. Create New Worktree

#### 3.1 Get Title (if not provided)

Use AskUserQuestion:

- "What is the feature title?"
- Example: "Add user authentication", "Fix login bug #123"

#### 3.2 Generate Slug from Title

Convert title to GitHub-friendly branch name:

```bash
SLUG=$(echo "$TITLE" | \
  tr '[:upper:]' '[:lower:]' | \
  sed 's/[^a-z0-9]/-/g' | \
  sed 's/--*/-/g' | \
  sed 's/^-//' | \
  sed 's/-$//')

echo "Generated slug: $SLUG"
```

Examples:

- "Add User Authentication" → `add-user-authentication`
- "Fix: Login Bug #123" → `fix-login-bug-123`
- "FEAT: New Dashboard" → `feat-new-dashboard`

#### 3.3 Create Branch and Worktree

```bash
git -C "$MAIN_PATH" fetch origin main
git -C "$MAIN_PATH" worktree add "$REPO_ROOT/$SLUG" -b "$SLUG" origin/main
```

If branch already exists (no worktree):

```bash
git -C "$MAIN_PATH" worktree add "$REPO_ROOT/$SLUG" "$SLUG"
```

#### 3.4 Copy Environment Files

Find all `.env.example` files and copy to `.env`:

```bash
cd "$REPO_ROOT/$SLUG"

find . -name ".env.example" -type f | while read example; do
  target="${example%.example}"
  if [ ! -f "$target" ]; then
    cp "$example" "$target"
    echo "Copied: $example → $target"
  else
    echo "Skipped (exists): $target"
  fi
done
```

#### 3.5 Install Dependencies

```bash
cd "$REPO_ROOT/$SLUG"
pnpm install
```

#### 3.6 Switch to Worktree

The working directory should now be in the new worktree:

```bash
cd "$REPO_ROOT/$SLUG"
pwd
```

#### 3.7 Rename Session

Rename the Claude session to match the slug for easy identification:

```
/rename <slug>
```

This makes it easy to find and resume this conversation later.

### 4. Output Summary

After creating, display:

```
Worktree created successfully!

  Path:   ~/workspace/<repo>/<slug>
  Branch: <slug>
  Source: ~/workspace/<repo>/main

Environment files copied:
  - .env
  - apps/web/.env

Dependencies installed via pnpm.

Ready to develop. Run /implementation-plan to create a plan.
```

After switching to existing, display:

```
Switched to worktree: <slug>

  Path:   ~/workspace/<repo>/<slug>
  Branch: <slug>

Run 'git status' to see current state.
```

## Edge Cases

### Worktree Already Exists for Slug

If the slug already exists as a worktree, ask user:

- Switch to existing worktree?
- Choose a different slug?

### Branch Exists Without Worktree

Create worktree from existing branch:

```bash
git -C "$MAIN_PATH" worktree add "$REPO_ROOT/$SLUG" "$SLUG"
```

### No .env.example Files Found

Just skip the copy step and note it in output.

### pnpm install Fails

Report the error but don't fail the entire operation. The worktree is still
usable.

## Quick Reference

```bash
# List all worktrees
git worktree list

# Remove a worktree (from main)
git -C ~/workspace/<repo>/main worktree remove ~/workspace/<repo>/<slug>

# Prune stale worktree references
git worktree prune

# Delete branch after removing worktree
git branch -d <slug>
```
