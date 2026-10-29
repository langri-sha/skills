#!/usr/bin/env bash
#
# create-worktree.sh — create or reuse a sibling worktree in a bare-repo layout.
#
# Usage: create-worktree.sh <slug-or-title>
#
# A title is turned into a kebab-case slug. The worktree lands at
# <repo>/<slug>, next to main/. Progress goes to stderr; the last line on
# stdout is the worktree path.
set -euo pipefail

arg="${1:?usage: create-worktree.sh <slug-or-title>}"
slug=$(printf '%s' "$arg" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')
[ -n "$slug" ] || { echo "Cannot derive a slug from: $arg" >&2; exit 1; }

common=$(git rev-parse --path-format=absolute --git-common-dir)
if [ "$(basename "$common")" != .bare ]; then
  echo "Not a bare-repo layout: the repository lives at $common, not <repo>/.bare." >&2
  exit 1
fi
root=$(dirname "$common")
path="$root/$slug"

if [ -d "$path" ]; then
  echo "Reusing the existing worktree $path" >&2
  echo "$path"
  exit 0
fi

git fetch --quiet origin main
if git show-ref --verify --quiet "refs/heads/$slug"; then
  git worktree add --quiet "$path" "$slug"
else
  git worktree add --quiet -b "$slug" "$path" origin/main
fi
echo "Created $path on branch $slug" >&2

cd "$path"
find . -name .env.example -type f | while read -r example; do
  target=${example%.example}
  if [ ! -e "$target" ]; then
    cp "$example" "$target"
    echo "Copied $example to $target" >&2
  fi
done

pnpm install >&2 || echo "pnpm install failed; the worktree is still usable." >&2

echo "$path"
