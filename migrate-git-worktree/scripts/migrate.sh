#!/usr/bin/env bash
#
# migrate.sh — Migrate git worktree layout from side-by-side to bare-repo.
#
# Before:
#   ~/src/repo/                    (main worktree / regular clone)
#   ~/src/repo.worktree/branch/    (feature worktrees)
#
# After:
#   ~/src/repo/.bare/              (bare repository)
#   ~/src/repo/.git                (file: "gitdir: ./.bare")
#   ~/src/repo/main/               (worktree for main branch)
#   ~/src/repo/branch/             (feature worktrees as siblings)
#
# Usage: migrate.sh [repo-path]
#   repo-path: path to the main worktree (default: detected from cwd)

set -euo pipefail

# --- Resolve source repo ---
if [[ $# -ge 1 ]]; then
  SOURCE_PATH="$(cd "$1" && pwd)"
else
  SOURCE_PATH="$(git worktree list | head -1 | awk '{print $1}')"
fi

REPO_NAME="$(basename "$SOURCE_PATH")"
WORKSPACE_ROOT="$(dirname "$SOURCE_PATH")"
WORKTREE_DIR="${WORKSPACE_ROOT}/${REPO_NAME}.worktree"
NEW_ROOT="${WORKSPACE_ROOT}/${REPO_NAME}"

echo "=== Git Worktree Layout Migration (bare-repo) ==="
echo ""
echo "  Source repo:    $SOURCE_PATH"
echo "  Repo name:      $REPO_NAME"
echo "  Worktree dir:   $WORKTREE_DIR"
echo "  New root:       $NEW_ROOT"
echo ""

# --- Detect HEAD state (branch or detached) ---
MAIN_HEAD_REF="$(git -C "$SOURCE_PATH" symbolic-ref HEAD 2>/dev/null || true)"
MAIN_HEAD_SHA="$(git -C "$SOURCE_PATH" rev-parse HEAD)"
if [[ -n "$MAIN_HEAD_REF" ]]; then
  echo "  Main HEAD:      $MAIN_HEAD_REF ($MAIN_HEAD_SHA)"
else
  echo "  Main HEAD:      detached at $MAIN_HEAD_SHA"
fi

# --- Collect linked worktrees (excluding main) ---
# Worktrees under $WORKTREE_DIR move next to main/; any other linked worktree
# stays where it is and only has its link to the repository rewritten.
declare -a WORKTREE_NAMES=()
declare -a OTHER_WORKTREES=()
first=1
while read -r key value; do
  [[ "$key" == worktree ]] || continue
  if [[ "$first" -eq 1 ]]; then
    first=0
    continue
  fi
  if [[ "$(dirname "$value")" == "$WORKTREE_DIR" ]]; then
    WORKTREE_NAMES+=("$(basename "$value")")
  else
    OTHER_WORKTREES+=("$value")
  fi
done < <(git -C "$SOURCE_PATH" worktree list --porcelain)

echo "  Worktrees found: $((${#WORKTREE_NAMES[@]} + ${#OTHER_WORKTREES[@]}))"
for name in "${WORKTREE_NAMES[@]}"; do
  echo "    - $name (moves next to main/)"
done
for wt in "${OTHER_WORKTREES[@]}"; do
  echo "    - $wt (stays in place)"
done
echo ""

# --- Check for dirty worktrees ---
DIRTY=()
if [[ -n "$(git -C "$SOURCE_PATH" status --porcelain 2>/dev/null)" ]]; then
  DIRTY+=("main ($SOURCE_PATH)")
fi
for name in "${WORKTREE_NAMES[@]}"; do
  wt_path="$WORKTREE_DIR/$name"
  if [[ -n "$(git -C "$wt_path" status --porcelain 2>/dev/null)" ]]; then
    DIRTY+=("$name ($wt_path)")
  fi
done
for wt in "${OTHER_WORKTREES[@]}"; do
  if [[ -n "$(git -C "$wt" status --porcelain 2>/dev/null)" ]]; then
    DIRTY+=("$wt")
  fi
done

if [[ ${#DIRTY[@]} -gt 0 ]]; then
  echo "WARNING: The following worktrees have uncommitted changes:"
  for d in "${DIRTY[@]}"; do
    echo "    - $d"
  done
  echo ""
  echo "Changes will be preserved but paths will change."
  echo "Press Enter to continue or Ctrl-C to abort."
  read -r
fi

# --- Step 1: Move existing linked worktrees into the repo directory ---
# Do this first while .git/ is still a directory, so git worktree move works.
if [[ ${#WORKTREE_NAMES[@]} -gt 0 ]]; then
  echo "Step 1: Moving linked worktrees into repo directory..."

  mkdir -p "$NEW_ROOT/.worktrees.tmp"
  for name in "${WORKTREE_NAMES[@]}"; do
    old_path="$WORKTREE_DIR/$name"
    new_path="$NEW_ROOT/.worktrees.tmp/$name"

    echo "  Moving worktree: $name"
    git -C "$SOURCE_PATH" worktree move "$old_path" "$new_path"
    echo "    $old_path -> $new_path"
  done
  echo ""

  # Remove old worktree directory if empty
  if [[ -d "$WORKTREE_DIR" ]]; then
    if [[ -z "$(ls -A "$WORKTREE_DIR" 2>/dev/null)" ]]; then
      rmdir "$WORKTREE_DIR"
      echo "  Removed empty: $WORKTREE_DIR"
    else
      echo "  WARNING: $WORKTREE_DIR is not empty, leaving in place"
    fi
  fi
else
  echo "Step 1: No linked worktrees to move."
fi
echo ""

# --- Step 2: Convert .git/ directory to .bare/ ---
echo "Step 2: Converting to bare repository..."

# Move .git/ to .bare/
mv "$SOURCE_PATH/.git" "$SOURCE_PATH/.bare"

# Set bare = true in config
git -C "$SOURCE_PATH/.bare" config core.bare true

# Set the bare repo HEAD to main branch (it no longer has a working tree)
echo "ref: refs/heads/main" > "$SOURCE_PATH/.bare/HEAD"

# Create .git file pointing to .bare
echo "gitdir: ./.bare" > "$SOURCE_PATH/.git"

echo "  Created: $SOURCE_PATH/.bare/ (bare repository)"
echo "  Created: $SOURCE_PATH/.git (gitdir pointer)"
echo ""

# --- Step 3: Fix worktree .git files ---
# After renaming .git/ to .bare/, linked worktree .git files still reference
# the old .git/worktrees/<name> path. Fix them before using git worktree move.
if [[ ${#WORKTREE_NAMES[@]} -gt 0 ]]; then
  echo "Step 3: Updating worktree references (.git/ -> .bare/)..."

  for name in "${WORKTREE_NAMES[@]}"; do
    wt_git_file="$NEW_ROOT/.worktrees.tmp/$name/.git"
    if [[ -f "$wt_git_file" ]]; then
      # Rewrite gitdir to point to .bare/worktrees/<name>
      echo "gitdir: $SOURCE_PATH/.bare/worktrees/$name" > "$wt_git_file"
      echo "  Fixed: $name/.git"
    fi
  done
  echo ""
else
  echo "Step 3: No worktree references to update."
  echo ""
fi

# Worktrees that stay in place point into .git/worktrees/<id> too.
for wt in "${OTHER_WORKTREES[@]}"; do
  gitdir="$(sed -n 's/^gitdir: //p' "$wt/.git")"
  echo "gitdir: $SOURCE_PATH/.bare/worktrees/${gitdir##*/}" > "$wt/.git"
  echo "  Relinked: $wt"
done

# --- Step 4: Create main/ worktree from existing working tree files ---
echo "Step 4: Creating main worktree..."

MAIN_WT_PATH="$NEW_ROOT/main"
WORKTREE_ID="main"

# Move all working tree files (not .bare, .git, .worktrees.tmp) into main/
mkdir -p "$MAIN_WT_PATH"
for item in "$SOURCE_PATH"/*; do
  base="$(basename "$item")"
  case "$base" in
    .bare|.git|.worktrees.tmp|main) continue ;;
  esac
  mv "$item" "$MAIN_WT_PATH/"
done

# Also move hidden files (except .bare, .git, .worktrees.tmp)
for item in "$SOURCE_PATH"/.*; do
  base="$(basename "$item")"
  case "$base" in
    .|..|.bare|.git|.worktrees.tmp) continue ;;
  esac
  mv "$item" "$MAIN_WT_PATH/"
done

# Register main/ as a linked worktree with the bare repo
mkdir -p "$SOURCE_PATH/.bare/worktrees/$WORKTREE_ID"

# gitdir: tells the bare repo where the worktree's .git file is
echo "$MAIN_WT_PATH/.git" > "$SOURCE_PATH/.bare/worktrees/$WORKTREE_ID/gitdir"

# HEAD: preserve the original state (detached or branch ref)
if [[ -n "$MAIN_HEAD_REF" ]]; then
  echo "ref: $MAIN_HEAD_REF" > "$SOURCE_PATH/.bare/worktrees/$WORKTREE_ID/HEAD"
else
  echo "$MAIN_HEAD_SHA" > "$SOURCE_PATH/.bare/worktrees/$WORKTREE_ID/HEAD"
fi

# commondir: tells git where the shared repo data lives (relative to worktrees/<id>/)
echo "../.." > "$SOURCE_PATH/.bare/worktrees/$WORKTREE_ID/commondir"

# Copy the index so the worktree doesn't see all files as deleted/untracked
if [[ -f "$SOURCE_PATH/.bare/index" ]]; then
  cp "$SOURCE_PATH/.bare/index" "$SOURCE_PATH/.bare/worktrees/$WORKTREE_ID/index"
fi

# Create .git file in the main worktree
echo "gitdir: $SOURCE_PATH/.bare/worktrees/$WORKTREE_ID" > "$MAIN_WT_PATH/.git"

echo "  Created worktree: $MAIN_WT_PATH"
echo ""

# --- Step 5: Move temporary worktrees to final locations ---
if [[ ${#WORKTREE_NAMES[@]} -gt 0 ]]; then
  echo "Step 5: Moving worktrees to final locations..."

  for name in "${WORKTREE_NAMES[@]}"; do
    tmp_path="$NEW_ROOT/.worktrees.tmp/$name"
    final_path="$NEW_ROOT/$name"

    echo "  Moving worktree: $name"
    git -C "$MAIN_WT_PATH" worktree move "$tmp_path" "$final_path"
    echo "    $tmp_path -> $final_path"
  done

  # Clean up temp directory
  rmdir "$NEW_ROOT/.worktrees.tmp" 2>/dev/null || true
  echo ""
else
  echo "Step 5: No linked worktrees to finalize."
  echo ""
fi

# Let git confirm both directions of every link it now holds.
REPAIR=("${OTHER_WORKTREES[@]}")
for name in "${WORKTREE_NAMES[@]}"; do
  REPAIR+=("$NEW_ROOT/$name")
done
git -C "$MAIN_WT_PATH" worktree repair "${REPAIR[@]}"

# --- Step 6: Verify remote configuration ---
# Bare repos cloned with --bare get a different default refspec.
# Since we converted from a regular clone, the refspec should already be correct,
# but verify it.
echo "Step 6: Verifying remote configuration..."
FETCH_REFSPEC="$(git -C "$SOURCE_PATH/.bare" config --get remote.origin.fetch 2>/dev/null || true)"
if [[ "$FETCH_REFSPEC" != "+refs/heads/*:refs/remotes/origin/*" ]]; then
  git -C "$SOURCE_PATH/.bare" config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
  echo "  Fixed fetch refspec for remote origin"
else
  echo "  Remote configuration OK"
fi
echo ""

# --- Done ---
echo "=== Migration complete ==="
echo ""
echo "New layout:"
echo "  $NEW_ROOT/"
echo "  ├── .bare/"
echo "  ├── .git"
echo "  ├── main/"
for name in "${WORKTREE_NAMES[@]}"; do
  echo "  ├── $name/"
done
for wt in "${OTHER_WORKTREES[@]}"; do
  echo "  Left in place: $wt"
done
echo ""
echo "Verify with: git -C '$MAIN_WT_PATH' worktree list"
