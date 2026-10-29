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

Convert a regular clone into the bare-repo layout: the repository moves to
`<repo>/.bare/`, `<repo>/.git` points at it, and every branch, the clone's own
included, is a worktree under `<repo>/`.

```
<repo>/.bare/       bare repository
<repo>/.git         "gitdir: ./.bare"
<repo>/main/        the clone's checkout, on whatever branch it had
<repo>/<branch>/    worktrees that lived in <repo>.worktree/
```

## Workflow

1. **Show the plan.** List the clone's linked worktrees with
   `git -C <repo> worktree list` and say where each ends up: worktrees under
   `<repo>.worktree/` move next to `main/`, and any other linked worktree stays
   where it is and is relinked. Wait for the user's go.
2. **Run the bundled script,** relative to this skill's directory:

   ```bash
   scripts/migrate.sh <repo>
   ```

   It stops before changing anything when a worktree has uncommitted changes.
   Those changes survive the move, so with the user's agreement rerun it with
   `--allow-dirty` before the path.

3. **Verify** with `git -C <repo>/main worktree list` and
   `git -C <repo>/main status`, then point the user at anything that named the
   old paths: editor workspaces, shell aliases, symlinks.
