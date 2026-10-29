#!/usr/bin/env bash
#
# run-tests.sh — fixture harness for scripts/reap.sh.
#
# Builds a throwaway bare-repo garden in a temp directory, exercises every
# classification branch against it, and asserts that dry runs change nothing
# and that apply removes only the landed, clean, idle worktrees.
#
# The harness never touches a real garden: every path it writes to lives under
# the mktemp directory it creates and removes on exit.
#
# Usage: run-tests.sh

set -euo pipefail

SKILL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
REAP="$SKILL_DIR/scripts/reap.sh"
[[ -x $REAP ]] || {
  printf 'run-tests.sh: %s is not executable\n' "$REAP" >&2
  exit 1
}

TMP=$(mktemp -d "${TMPDIR:-/tmp}/worktree-reaper-tests.XXXXXX")
GARDEN="$TMP/garden"
BARE="$GARDEN/.bare"
SEED="$TMP/seed"
ORIGIN="$TMP/origin.git"
SLEEPER=""

cleanup() {
  local status=$?
  if [[ -n $SLEEPER ]]; then
    kill "$SLEEPER" 2>/dev/null || true
    wait "$SLEEPER" 2>/dev/null || true
  fi
  if [[ -d $GARDEN ]]; then
    git -C "$BARE" worktree unlock "$GARDEN/wtr-locked" >/dev/null 2>&1 || true
  fi
  if [[ $TMP == /*/worktree-reaper-tests.* && -d $TMP ]]; then
    rm -rf -- "$TMP"
  fi
  exit "$status"
}
trap cleanup EXIT

export HOME="$TMP/home"
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_SYSTEM=/dev/null
export GIT_AUTHOR_NAME="Worktree Reaper Tests"
export GIT_AUTHOR_EMAIL="tests@example.invalid"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
mkdir -p "$HOME"
export PATH="$TMP/bin:$PATH"
export HERDR_STUB_STATE=up

PASSED=0
FAILED=0

pass() {
  PASSED=$((PASSED + 1))
  printf '  ok   %s\n' "$1"
}

fail() {
  FAILED=$((FAILED + 1))
  printf '  FAIL %s\n' "$1"
  if [[ $# -gt 1 ]]; then
    printf '       %s\n' "$2"
  fi
}

check() {
  local label=$1 condition=$2 detail=${3:-}
  if [[ $condition == true ]]; then
    pass "$label"
  else
    fail "$label" "$detail"
  fi
}

row_for() {
  awk -v slug="$2" '$2 == slug { print; exit }' <<<"$1"
}

expect_verdict() {
  local output=$1 slug=$2 want=$3 row got
  row=$(row_for "$output" "$slug")
  if [[ -z $row ]]; then
    fail "$slug is reported" "no row found for $slug"
    return
  fi
  got=$(awk '{print $1}' <<<"$row")
  if [[ $got == "$want" ]]; then
    pass "$slug → $want"
  else
    fail "$slug → $want" "got '$got' in: $row"
  fi
}

expect_reason() {
  local output=$1 slug=$2 want=$3 row
  row=$(row_for "$output" "$slug")
  if [[ $row == *"$want"* ]]; then
    pass "$slug reason mentions '$want'"
  else
    fail "$slug reason mentions '$want'" "got: ${row:-<no row>}"
  fi
}

expect_output() {
  local output=$1 want=$2
  if [[ $output == *"$want"* ]]; then
    pass "output mentions '$want'"
  else
    fail "output mentions '$want'"
  fi
}

expect_missing() {
  local output=$1 want=$2
  if [[ $output != *"$want"* ]]; then
    pass "output omits '$want'"
  else
    fail "output omits '$want'"
  fi
}

commit_file() {
  local repo=$1 name=$2 body=$3
  printf '%s\n' "$body" >"$repo/$name"
  git -C "$repo" add -- "$name"
  git -C "$repo" commit -qm "Add $name"
}

build_fixture() {
  git init -q --bare -b main "$ORIGIN"
  git clone -q "$ORIGIN" "$SEED" 2>/dev/null

  printf 'node_modules/\n' >"$SEED/.gitignore"
  printf 'garden\n' >"$SEED/README.md"
  git -C "$SEED" add -A
  git -C "$SEED" commit -qm "Seed the garden"
  git -C "$SEED" push -q origin main

  git -C "$SEED" checkout -q -b wtr-landed-rebase
  commit_file "$SEED" "landed.txt" "landed work"
  local landed_sha
  landed_sha=$(git -C "$SEED" rev-parse HEAD)
  git -C "$SEED" push -q origin wtr-landed-rebase

  git -C "$SEED" checkout -q main
  commit_file "$SEED" "unrelated.txt" "moved main forward"
  git -C "$SEED" cherry-pick "$landed_sha" >/dev/null
  git -C "$SEED" push -q origin main

  git -C "$SEED" checkout -q -b wtr-unmerged main~2
  commit_file "$SEED" "unmerged.txt" "never landed"
  git -C "$SEED" push -q origin wtr-unmerged

  git -C "$SEED" checkout -q -b wtr-empty-retrigger main
  git -C "$SEED" commit -q --allow-empty -m "Retrigger CI"
  git -C "$SEED" push -q origin wtr-empty-retrigger

  # A change that landed on main and was then reverted, plus a branch carrying
  # the same patch. Patch-id detection sees the upstream twin and misses the
  # revert — this fixture pins that known limitation.
  git -C "$SEED" checkout -q main
  local before_revert
  before_revert=$(git -C "$SEED" rev-parse HEAD)
  commit_file "$SEED" "reverted.txt" "landed then reverted"
  git -C "$SEED" revert --no-edit HEAD >/dev/null
  git -C "$SEED" push -q origin main
  git -C "$SEED" checkout -q -b wtr-revert-victim "$before_revert"
  commit_file "$SEED" "reverted.txt" "landed then reverted"
  git -C "$SEED" push -q origin wtr-revert-victim

  # trunk carries main's content under a different name, so a --primary that is
  # not "main" would leave main/ eligible without the hard protection.
  git -C "$SEED" checkout -q -b trunk main
  git -C "$SEED" push -q origin trunk

  git clone -q --bare "$ORIGIN" "$BARE"
  git -C "$BARE" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
  git -C "$BARE" fetch -q origin
  printf 'gitdir: ./.bare\n' >"$GARDEN/.git"

  git -C "$BARE" worktree add "$GARDEN/main" main >/dev/null 2>&1
  git -C "$BARE" worktree add "$GARDEN/wtr-landed-rebase" wtr-landed-rebase >/dev/null 2>&1
  git -C "$BARE" worktree add "$GARDEN/wtr-unmerged" wtr-unmerged >/dev/null 2>&1
  git -C "$BARE" worktree add "$GARDEN/wtr-empty-retrigger" wtr-empty-retrigger >/dev/null 2>&1
  git -C "$BARE" worktree add "$GARDEN/wtr-revert-victim" wtr-revert-victim >/dev/null 2>&1

  local idle
  for idle in wtr-no-unique wtr-ignored wtr-dirty wtr-untracked wtr-locked wtr-active wtr-ghost \
    wtr-herdr-pane wtr-herdr-tab wtr-herdr-workspace; do
    git -C "$BARE" branch "$idle" origin/main >/dev/null 2>&1
    git -C "$BARE" worktree add "$GARDEN/$idle" "$idle" >/dev/null 2>&1
  done

  git -C "$BARE" worktree add --detach "$GARDEN/wtr-detached" origin/main >/dev/null 2>&1
  git -C "$BARE" worktree add "$GARDEN/.claude/worktrees/wtr-agent" \
    -b wtr-agent origin/main >/dev/null 2>&1
  git -C "$BARE" worktree add "$TMP/outside/wtr-stray" \
    -b wtr-stray origin/main >/dev/null 2>&1

  mkdir -p "$GARDEN/wtr-ignored/node_modules"
  head -c 262144 /dev/zero >"$GARDEN/wtr-ignored/node_modules/blob.bin"

  printf 'local edit\n' >>"$GARDEN/wtr-dirty/README.md"
  printf 'scratch\n' >"$GARDEN/wtr-untracked/scratch.txt"
  git -C "$BARE" worktree lock "$GARDEN/wtr-locked" >/dev/null 2>&1

  rm -rf -- "$GARDEN/wtr-ghost"
}

write_herdr_stub() {
  mkdir -p "$TMP/bin"
  cat >"$TMP/bin/herdr" <<STUB
#!/usr/bin/env bash
if [[ \$HERDR_STUB_STATE == down ]]; then
  printf '%s\n' '{"error":{"code":"server_not_running","message":"no herdr server is running"}}' >&2
  exit 1
fi
case "\$1 \$2" in
  "pane list") printf '%s\n' '{"result":{"panes":[{"pane_id":"w1:p1","cwd":"$GARDEN/wtr-herdr-pane/src"}]}}' ;;
  "tab list") printf '%s\n' '{"result":{"tabs":[{"tab_id":"w1:t1","label":"wtr-herdr-tab"}]}}' ;;
  "workspace list") printf '%s\n' '{"result":{"workspaces":[{"workspace_id":"w1","label":"wtr-herdr-workspace"}]}}' ;;
  *) exit 2 ;;
esac
STUB
  chmod +x "$TMP/bin/herdr"
}

garden_state() {
  git -C "$BARE" worktree list --porcelain
  find "$GARDEN" -maxdepth 1 -mindepth 1 | sort
}

printf 'worktree-reaper fixture tests\n\n'
printf 'Building fixture garden in %s\n' "$TMP"
build_fixture
write_herdr_stub

printf 'Holding wtr-active busy with a process whose cwd is inside it\n'
(cd "$GARDEN/wtr-active" && exec sleep 300) &
SLEEPER=$!
sleep 0.3

printf '\nDry run\n'
BEFORE=$(garden_state)
DRY=$("$REAP" --garden "$GARDEN" --all-sizes 2>&1)
AFTER=$(garden_state)

check "dry run leaves the garden untouched" \
  "$([[ $BEFORE == "$AFTER" ]] && printf true || printf false)" \
  "worktree list or garden contents changed"

expect_verdict "$DRY" ".bare" keep
expect_verdict "$DRY" "main" keep
expect_verdict "$DRY" "wtr-landed-rebase" reap
expect_verdict "$DRY" "wtr-no-unique" reap
expect_verdict "$DRY" "wtr-ignored" reap
expect_verdict "$DRY" "wtr-unmerged" skip
expect_verdict "$DRY" "wtr-empty-retrigger" reap
expect_verdict "$DRY" "wtr-dirty" skip
expect_verdict "$DRY" "wtr-untracked" skip
expect_verdict "$DRY" "wtr-locked" skip
expect_verdict "$DRY" "wtr-active" skip
expect_verdict "$DRY" "wtr-herdr-pane" skip
expect_verdict "$DRY" "wtr-herdr-tab" skip
expect_verdict "$DRY" "wtr-herdr-workspace" skip
expect_verdict "$DRY" "wtr-detached" skip
expect_verdict "$DRY" "wtr-ghost" skip
expect_verdict "$DRY" ".claude/worktrees/wtr-agent" skip
expect_verdict "$DRY" "$TMP/outside/wtr-stray" skip

expect_reason "$DRY" "wtr-landed-rebase" "patch-equivalent"
expect_reason "$DRY" "wtr-no-unique" "no unique commits"
expect_reason "$DRY" "wtr-unmerged" "not landed on origin/main"
expect_reason "$DRY" "wtr-empty-retrigger" "1 empty commit(s) ignored"
expect_reason "$DRY" "wtr-dirty" "uncommitted or untracked"
expect_reason "$DRY" "wtr-untracked" "uncommitted or untracked"
expect_reason "$DRY" "wtr-locked" "locked"
expect_reason "$DRY" "wtr-active" "in use by"
expect_reason "$DRY" "wtr-herdr-pane" "herdr pane"
expect_reason "$DRY" "wtr-herdr-tab" "herdr tab 'wtr-herdr-tab'"
expect_reason "$DRY" "wtr-herdr-workspace" "herdr workspace 'wtr-herdr-workspace'"
expect_reason "$DRY" "wtr-detached" "detached HEAD"
expect_reason "$DRY" "wtr-ghost" "directory is missing"
expect_reason "$DRY" ".claude/worktrees/wtr-agent" "agent-managed nested worktree"
expect_reason "$DRY" "$TMP/outside/wtr-stray" "outside the garden root"
expect_reason "$DRY" "main" "primary worktree"
expect_reason "$DRY" ".bare" "bare repository"

expect_output "$DRY" "Git objects live once in .bare/"
expect_output "$DRY" "in-use scan"
expect_output "$DRY" "process cwds"
expect_output "$DRY" "1 herdr tab(s)"
expect_output "$DRY" "Dry run — nothing was touched"
expect_missing "$DRY" "Pruned stale worktree metadata"

IGNORED_ROW=$(row_for "$DRY" "wtr-ignored")
check "ignored node_modules counts toward reclaimable size" \
  "$([[ $IGNORED_ROW == *KiB* || $IGNORED_ROW == *MiB* ]] && printf true || printf false)" \
  "row read as '$IGNORED_ROW'"

printf '\nA Herdr server that is not running holds nothing\n'
HERDR_DOWN=$(HERDR_STUB_STATE=down "$REAP" --garden "$GARDEN" 2>&1)
expect_output "$HERDR_DOWN" "no herdr server"
expect_verdict "$HERDR_DOWN" "wtr-herdr-pane" reap
expect_verdict "$HERDR_DOWN" "wtr-herdr-tab" reap
expect_verdict "$HERDR_DOWN" "wtr-herdr-workspace" reap

printf '\nBranch name that differs from the directory name\n'
git -C "$BARE" branch -m wtr-no-unique wtr-renamed >/dev/null 2>&1
RENAMED=$("$REAP" --garden "$GARDEN" 2>&1)
expect_verdict "$RENAMED" "wtr-no-unique" reap
expect_output "$RENAMED" "wtr-no-unique [wtr-renamed]"
git -C "$BARE" branch -m wtr-renamed wtr-no-unique >/dev/null 2>&1

printf '\nmain/ stays protected under a non-main --primary\n'
TRUNK=$("$REAP" --garden "$GARDEN" --primary origin/trunk 2>&1)
expect_verdict "$TRUNK" "main" keep
expect_reason "$TRUNK" "main" "default-branch worktree"

printf '\nKnown limitation: a reverted-upstream patch still reads as landed\n'
expect_verdict "$DRY" "wtr-revert-victim" reap
check "the revert victim keeps its branch, so removal is recoverable" \
  "$(git -C "$BARE" rev-parse --verify --quiet refs/heads/wtr-revert-victim >/dev/null && printf true || printf false)" \
  "branch wtr-revert-victim is missing from the fixture"

printf '\n--strict-commits restores the commit-for-commit veto\n'
STRICT=$("$REAP" --garden "$GARDEN" --strict-commits 2>&1)
expect_verdict "$STRICT" "wtr-empty-retrigger" skip
expect_reason "$STRICT" "wtr-empty-retrigger" "held back by --strict-commits"
expect_verdict "$STRICT" "wtr-unmerged" skip
expect_verdict "$STRICT" "wtr-landed-rebase" reap

printf '\nCurrent worktree protection\n'
CURRENT=$(cd "$GARDEN/wtr-ignored" && "$REAP" --garden "$GARDEN" 2>&1)
expect_verdict "$CURRENT" "wtr-ignored" keep
expect_reason "$CURRENT" "wtr-ignored" "current worktree"

printf '\nRefusals\n'
BAD_LAYOUT=$("$REAP" --garden "$SEED" 2>&1 || true)
expect_output "$BAD_LAYOUT" "is not a bare-repo worktree garden"

set +e
"$REAP" --garden "$SEED" >/dev/null 2>&1
BAD_STATUS=$?
"$REAP" --garden "$GARDEN" --nonsense >/dev/null 2>&1
ARG_STATUS=$?
"$REAP" --help >/dev/null 2>&1
HELP_STATUS=$?
UNCONFIRMED=$("$REAP" --garden "$GARDEN" --apply 2>&1 </dev/null)
UNCONFIRMED_STATUS=$?
set -e

check "malformed layout exits 1" \
  "$([[ $BAD_STATUS -eq 1 ]] && printf true || printf false)" "exit $BAD_STATUS"
check "unknown argument exits 1" \
  "$([[ $ARG_STATUS -eq 1 ]] && printf true || printf false)" "exit $ARG_STATUS"
check "--help exits 0" \
  "$([[ $HELP_STATUS -eq 0 ]] && printf true || printf false)" "exit $HELP_STATUS"
check "unconfirmed apply exits 1" \
  "$([[ $UNCONFIRMED_STATUS -eq 1 ]] && printf true || printf false)" "exit $UNCONFIRMED_STATUS"
expect_output "$UNCONFIRMED" "aborted at the confirmation prompt"
check "unconfirmed apply removed nothing" \
  "$([[ -d $GARDEN/wtr-landed-rebase ]] && printf true || printf false)" \
  "wtr-landed-rebase disappeared without a confirmation"

printf '\nApply\n'
APPLIED=$(printf 'y\n' | "$REAP" --garden "$GARDEN" --apply 2>&1)

for gone in wtr-landed-rebase wtr-no-unique wtr-ignored wtr-revert-victim wtr-empty-retrigger; do
  check "$gone was removed" \
    "$([[ ! -e $GARDEN/$gone ]] && printf true || printf false)" \
    "$GARDEN/$gone still exists"
done

for kept in main wtr-unmerged wtr-dirty wtr-untracked wtr-locked wtr-active wtr-detached \
  wtr-herdr-pane wtr-herdr-tab wtr-herdr-workspace; do
  check "$kept survived apply" \
    "$([[ -d $GARDEN/$kept ]] && printf true || printf false)" \
    "$GARDEN/$kept is gone"
done

check "the bare repository survived apply" \
  "$([[ -d $BARE ]] && printf true || printf false)" "$BARE is gone"
check "the nested agent worktree survived apply" \
  "$([[ -d $GARDEN/.claude/worktrees/wtr-agent ]] && printf true || printf false)" \
  "nested agent worktree was removed"
check "the worktree outside the garden survived apply" \
  "$([[ -d $TMP/outside/wtr-stray ]] && printf true || printf false)" \
  "out-of-garden worktree was removed"

for branch in wtr-landed-rebase wtr-no-unique wtr-ignored wtr-revert-victim; do
  check "branch $branch survived removal" \
    "$(git -C "$BARE" rev-parse --verify --quiet "refs/heads/$branch" >/dev/null && printf true || printf false)" \
    "branch $branch was deleted"
done

expect_output "$APPLIED" "Removed 5 worktree(s)"
expect_output "$APPLIED" "Pruned stale worktree metadata."
expect_output "$APPLIED" "Branches were kept."
check "the stale ghost entry was pruned after removals" \
  "$(git -C "$BARE" worktree list --porcelain | grep -q "wtr-ghost" && printf false || printf true)" \
  "wtr-ghost is still registered"

printf '\nPrune stays tied to a successful removal\n'
git -C "$BARE" branch wtr-ghost2 origin/main >/dev/null 2>&1
git -C "$BARE" worktree add "$GARDEN/wtr-ghost2" wtr-ghost2 >/dev/null 2>&1
rm -rf -- "$GARDEN/wtr-ghost2"
NOOP=$(printf 'y\n' | "$REAP" --garden "$GARDEN" --apply 2>&1)
expect_output "$NOOP" "Nothing to remove."
expect_missing "$NOOP" "Pruned stale worktree metadata."
check "a no-op apply leaves stale metadata alone" \
  "$(git -C "$BARE" worktree list --porcelain | grep -q "wtr-ghost2" && printf true || printf false)" \
  "wtr-ghost2 was pruned without any removal"

printf '\n%s passed, %s failed\n' "$PASSED" "$FAILED"
[[ $FAILED -eq 0 ]]
