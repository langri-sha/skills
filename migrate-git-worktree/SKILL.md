---
name: migrate-git-worktree
description:
  Migrate a git worktree layout from the side-by-side convention (repo/ +
  repo.worktree/branch/) to a bare-repo convention where the repo directory
  contains a bare clone at .bare/, a .git file pointing to it, and all branches
  (including main) as worktree subdirectories. Use when the user wants to
  reorganize their worktree folder structure.
metadata:
  author: langri-sha
  version: '2.0.0'
  argument-hint: '[repo-path]'
---

# Migrate Git Worktree Layout

Migrate from the side-by-side worktree convention to a bare-repo layout where
`.bare/` holds the repository and all branches are equal-status worktrees.

## Layout Comparison

**Before (side-by-side):**

```
~/workspace/myrepo/                    # main worktree (regular clone)
~/workspace/myrepo.worktree/           # worktree container
~/workspace/myrepo.worktree/feature-a/ # feature worktree
~/workspace/myrepo.worktree/feature-b/ # feature worktree
```

**After (bare-repo):**

```
~/workspace/myrepo/                    # parent directory
~/workspace/myrepo/.bare/              # bare repository (all objects, refs)
~/workspace/myrepo/.git                # file: "gitdir: ./.bare"
~/workspace/myrepo/main/               # worktree for main branch
~/workspace/myrepo/feature-a/          # worktree
~/workspace/myrepo/feature-b/          # worktree
```

## How It Works

The `.bare/` directory is a bare git repository containing all objects, refs,
and history. The `.git` file at the repo root is a gitdir pointer that lets git
commands work from the parent directory. Every branch — including main — is a
linked worktree. No branch is special.

Key properties:

- `.bare/` contains the repository data (equivalent to a `.git/` directory)
- `.git` is a file (not a directory) containing `gitdir: ./.bare`
- All branches are worktrees, including `main`
- Worktrees are siblings under the parent directory
- `git worktree add/remove` works from any worktree

Reference:
https://morgan.cugerone.com/blog/how-to-use-git-worktree-and-in-a-clean-way/

## Migration Workflow

### 1. Detect Current Layout

Determine the source repo path and any existing worktrees:

```bash
SOURCE_PATH=$(git worktree list | head -1 | awk '{print $1}')
REPO_NAME=$(basename "$SOURCE_PATH")
WORKSPACE_ROOT=$(dirname "$SOURCE_PATH")
WORKTREE_DIR="${WORKSPACE_ROOT}/${REPO_NAME}.worktree"
```

### 2. Confirm with User

Before proceeding, display the migration plan and confirm via AskUserQuestion:

```
Migration plan:

  Current main:  ~/workspace/myrepo
  Worktree dir:  ~/workspace/myrepo.worktree/

  New layout:
    ~/workspace/myrepo/.bare/             (bare repository)
    ~/workspace/myrepo/.git               (gitdir pointer)
    ~/workspace/myrepo/main/              (worktree — was ~/workspace/myrepo)
    ~/workspace/myrepo/feature-a/         (worktree — was ~/workspace/myrepo.worktree/feature-a)

  Proceed?
```

### 3. Run Migration Script

Execute the migration script bundled with this skill (`scripts/migrate.sh`,
resolved relative to this skill's base directory):

```bash
bash <skill-base-dir>/scripts/migrate.sh "$SOURCE_PATH"
```

Or run the steps manually if the script is not available — see the script source
for the full procedure.

### 4. Post-Migration

After migration completes:

1. Verify the layout with `git -C <repo>/main worktree list`
2. Update any IDE workspace or shell aliases that reference the old paths
3. The old `.worktree/` directory is removed if empty

### 5. Adding New Worktrees

After migrating, new worktrees are added from any existing worktree:

```bash
cd ~/workspace/myrepo/main
git worktree add ../new-feature -b new-feature origin/main
```

## Edge Cases

### Dirty Working Trees

If any worktree has uncommitted changes, warn the user and ask whether to
proceed. The migration moves directories — uncommitted work is preserved but
paths change.

### Worktree Path References

Each worktree contains a `.git` file pointing to `.bare/worktrees/<name>`. The
migration script updates these references. If migrating manually, update:

- `<worktree>/.git` (points to `.bare/worktrees/<name>`)
- `.bare/worktrees/<name>/gitdir` (points to worktree)

### No Existing Worktrees

If there is no `.worktree/` directory, convert the repo in place:

1. Move `.git/` to `.bare/`
2. Set `bare = true` in `.bare/config`
3. Create `.git` file with `gitdir: ./.bare`
4. Move working tree files into a `main/` worktree

## Resources

- **`scripts/migrate.sh`** — Migration script that handles the full conversion
  from side-by-side to bare-repo layout
