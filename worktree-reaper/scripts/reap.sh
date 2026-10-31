#!/usr/bin/env bash
#
# reap.sh — inventory the worktrees of a bare-repo garden and reclaim disk
# space by removing the ones whose branch has confidently landed on the
# primary remote branch.
#
# Expected layout (see the create-worktree skill):
#
#   <garden>/.bare/     bare repository — all objects and refs
#   <garden>/.git       file: "gitdir: ./.bare"
#   <garden>/main/      worktree for the primary branch
#   <garden>/<slug>/    feature worktrees, siblings of main/
#
# Dry run by default: it classifies and measures, and changes nothing. Removal
# needs --apply plus a typed confirmation, always goes through
# `git worktree remove` without --force, and never deletes a branch.
#
# Usage: reap.sh [options]   (reap.sh --help)

set -euo pipefail

PRIMARY_REF="origin/main"
GARDEN=""
DO_FETCH=0
ALL_SIZES=0
APPLY=0
PR_EVIDENCE=1
STRICT_COMMITS=0

usage() {
  cat <<'EOF'
Usage: reap.sh [options]

Inventories every worktree of a bare-repo garden, reports the disk each one
holds, and removes only those whose branch has confidently landed on the
primary remote branch.

Options:
  --garden PATH      Garden root holding .bare/ (default: derived from cwd)
  --primary REF      Remote branch that defines "landed" (default: origin/main)
  --fetch            Refresh the primary ref first (all a dry run ever writes)
  --all-sizes        Measure every worktree, not just reap candidates
  --no-pr-evidence   Skip the `gh pr list` corroboration lookup
  --strict-commits   Require every commit to have an upstream twin, including
                     ones that change nothing. Rebase-merge drops empty commits,
                     so this holds back any branch that ever needed a CI
                     retrigger — even when all of its work landed
  --apply            Remove reap candidates after a typed confirmation
  -h, --help         Show this help

Dry run is the default and the mode meant for periodic use. --apply always
prompts for confirmation on stdin, so an unattended run cannot remove anything.

Exit codes: 0 success, 1 usage or safety refusal, 2 one or more removals failed.
EOF
}

die() {
  printf 'reap.sh: %s\n' "$1" >&2
  exit "${2:-1}"
}

abspath() {
  readlink -f -- "$1"
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --garden)
      [[ $# -ge 2 ]] || die "--garden requires a value"
      GARDEN=$2
      shift 2
      ;;
    --primary)
      [[ $# -ge 2 ]] || die "--primary requires a value"
      PRIMARY_REF=$2
      shift 2
      ;;
    --fetch)
      DO_FETCH=1
      shift
      ;;
    --all-sizes)
      ALL_SIZES=1
      shift
      ;;
    --no-pr-evidence)
      PR_EVIDENCE=0
      shift
      ;;
    --strict-commits)
      STRICT_COMMITS=1
      shift
      ;;
    --apply)
      APPLY=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "unknown argument: $1"
      ;;
  esac
done

if [[ -n $GARDEN ]]; then
  [[ -d $GARDEN ]] || die "--garden is not a directory: $GARDEN"
  GARDEN=$(abspath "$GARDEN")
else
  common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) ||
    die "not inside a git repository: $PWD"
  GARDEN=$(dirname "$(abspath "$common")")
fi

BARE_DIR="$GARDEN/.bare"
GIT_FILE="$GARDEN/.git"

layout_error() {
  die "$GARDEN is not a bare-repo worktree garden ($1). Refusing to touch it."
}

[[ -d $BARE_DIR ]] || layout_error "no .bare/ directory"
[[ -f $GIT_FILE ]] || layout_error "no .git gitdir pointer file"
BARE_DIR=$(abspath "$BARE_DIR")
[[ $(dirname "$BARE_DIR") == "$GARDEN" ]] ||
  layout_error ".bare/ resolves outside the garden root"

gitdir_line=$(<"$GIT_FILE")
[[ $gitdir_line == gitdir:* ]] || layout_error ".git holds no gitdir pointer"
gitdir_target=${gitdir_line#gitdir:}
gitdir_target=${gitdir_target#"${gitdir_target%%[![:space:]]*}"}
case $gitdir_target in
  /*) gitdir_target=$(abspath "$gitdir_target") ;;
  *) gitdir_target=$(abspath "$GARDEN/$gitdir_target") ;;
esac
[[ $gitdir_target == "$BARE_DIR" ]] || layout_error ".git does not point at .bare/"

[[ $(git -C "$BARE_DIR" rev-parse --is-bare-repository 2>/dev/null) == true ]] ||
  layout_error ".bare/ is not a bare repository"
common_dir=$(abspath "$(git -C "$BARE_DIR" rev-parse --path-format=absolute --git-common-dir)")
[[ $common_dir == "$BARE_DIR" ]] || layout_error "unexpected git common directory"

PRIMARY_BRANCH=${PRIMARY_REF##*/}
[[ -n $PRIMARY_BRANCH ]] || die "no branch name in --primary $PRIMARY_REF"

DEFAULT_BRANCH=$(git -C "$BARE_DIR" symbolic-ref --short HEAD 2>/dev/null || printf 'main')
PROTECTED_BRANCHES="|$PRIMARY_BRANCH|$DEFAULT_BRANCH|main|"

is_protected_name() {
  [[ -n $1 && $PROTECTED_BRANCHES == *"|$1|"* ]]
}

if ((DO_FETCH)); then
  fetch_remote=${PRIMARY_REF%%/*}
  fetch_branch=${PRIMARY_REF#*/}
  if [[ $fetch_remote == "$PRIMARY_REF" || -z $fetch_branch ]]; then
    die "--fetch needs --primary as <remote>/<branch>, got: $PRIMARY_REF"
  fi
  git -C "$BARE_DIR" fetch --quiet -- "$fetch_remote" "$fetch_branch" ||
    die "failed to fetch $fetch_remote $fetch_branch"
fi

PRIMARY_SHA=""
for candidate in "refs/remotes/$PRIMARY_REF" "$PRIMARY_REF"; do
  if PRIMARY_SHA=$(git -C "$BARE_DIR" rev-parse --verify --quiet "${candidate}^{commit}" 2>/dev/null); then
    break
  fi
  PRIMARY_SHA=""
done
[[ -n $PRIMARY_SHA ]] ||
  die "primary ref '$PRIMARY_REF' does not resolve to exactly one commit — fetch it, or pass --primary"

PRIMARY_DATE=$(git -C "$BARE_DIR" log -1 --format=%cd --date=format:'%Y-%m-%d %H:%M' "$PRIMARY_SHA")
PRIMARY_AGE_DAYS=$(( ($(date +%s) - $(git -C "$BARE_DIR" log -1 --format=%ct "$PRIMARY_SHA")) / 86400 ))

PRIMARY_WT="$GARDEN/$PRIMARY_BRANCH"
GIT_HOST_DIR="$BARE_DIR"
if [[ -d $PRIMARY_WT ]]; then
  GIT_HOST_DIR="$PRIMARY_WT"
fi

CURRENT_WT=""
if current_top=$(git rev-parse --show-toplevel 2>/dev/null); then
  CURRENT_WT=$(abspath "$current_top")
fi

GH_REPO=""
PR_EVIDENCE_NOTE="disabled (--no-pr-evidence)"
if ((PR_EVIDENCE)); then
  if ! command -v gh >/dev/null 2>&1; then
    PR_EVIDENCE=0
    PR_EVIDENCE_NOTE="unavailable (gh not installed)"
  else
    origin_url=$(git -C "$BARE_DIR" remote get-url origin 2>/dev/null || printf '')
    if [[ $origin_url =~ github\.com[:/]([^/]+)/(.+)$ ]]; then
      GH_REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]%.git}"
      PR_EVIDENCE_NOTE="gh pr list on $GH_REPO"
    else
      PR_EVIDENCE=0
      PR_EVIDENCE_NOTE="unavailable (origin is not a GitHub remote)"
    fi
  fi
fi

declare -a ACTIVE_DIRS=() ACTIVE_LABELS=() TMUX_WINDOWS=() HERDR_TABS=() HERDR_WORKSPACES=()
declare -a HC_TABS=() HC_SPACES=()
ACTIVITY_NOTE=""

note_activity_source() {
  ACTIVITY_NOTE=${ACTIVITY_NOTE:+$ACTIVITY_NOTE, }$1
}

collect_activity() {
  local pane name pid cwd comm panes terminals
  ACTIVE_DIRS=()
  ACTIVE_LABELS=()
  TMUX_WINDOWS=()
  HERDR_TABS=()
  HERDR_WORKSPACES=()
  HC_TABS=()
  HC_SPACES=()
  ACTIVITY_NOTE=""
  if command -v tmux >/dev/null 2>&1; then
    while IFS= read -r pane; do
      [[ -n $pane ]] || continue
      ACTIVE_DIRS+=("$pane")
      ACTIVE_LABELS+=("tmux pane")
    done < <(tmux list-panes -a -F '#{pane_current_path}' 2>/dev/null || true)
    while IFS= read -r name; do
      [[ -n $name ]] || continue
      TMUX_WINDOWS+=("$name")
    done < <(tmux list-windows -a -F '#{window_name}' 2>/dev/null || true)
    note_activity_source "${#TMUX_WINDOWS[@]} tmux window(s)"
  else
    note_activity_source "no tmux"
  fi

  if ! command -v herdr >/dev/null 2>&1; then
    note_activity_source "no herdr"
  elif ! command -v jq >/dev/null 2>&1; then
    note_activity_source "herdr UNAVAILABLE (no jq)"
  elif panes=$(herdr pane list 2>/dev/null); then
    while IFS= read -r pane; do
      [[ -n $pane ]] || continue
      ACTIVE_DIRS+=("$pane")
      ACTIVE_LABELS+=("herdr pane")
    done < <(jq -r '.result.panes[].cwd // empty' <<<"$panes" 2>/dev/null || true)
    while IFS= read -r name; do
      [[ -n $name ]] || continue
      HERDR_TABS+=("$name")
    done < <(herdr tab list 2>/dev/null | jq -r '.result.tabs[].label // empty' 2>/dev/null || true)
    while IFS= read -r name; do
      [[ -n $name ]] || continue
      HERDR_WORKSPACES+=("$name")
    done < <(herdr workspace list 2>/dev/null | jq -r '.result.workspaces[].label // empty' 2>/dev/null || true)
    note_activity_source "${#HERDR_TABS[@]} herdr tab(s)"
  else
    note_activity_source "no herdr server"
  fi

  if ! command -v hc >/dev/null 2>&1; then
    note_activity_source "no hc"
  elif ! command -v jq >/dev/null 2>&1; then
    note_activity_source "hc UNAVAILABLE (no jq)"
  elif terminals=$(hc ls --json 2>/dev/null); then
    while IFS= read -r cwd; do
      [[ -n $cwd ]] || continue
      ACTIVE_DIRS+=("$cwd")
      ACTIVE_LABELS+=("hc terminal")
    done < <(jq -r '.terminals[] | select(.state == "live" and (.address | contains("/") | not)) | .cwd // empty' <<<"$terminals" 2>/dev/null || true)
    while IFS= read -r name; do
      [[ -n $name ]] || continue
      HC_TABS+=("$name")
    done < <(jq -r '[.terminals[] | select(.state == "live") | .where // empty | select(contains(" / ")) | sub("^.* / "; "")] | unique[]' <<<"$terminals" 2>/dev/null || true)
    while IFS= read -r name; do
      [[ -n $name ]] || continue
      HC_SPACES+=("$name")
    done < <(jq -r '[.terminals[] | select(.state == "live") | .where // empty | select(contains(" / ")) | sub(" / .*$"; "")] | unique[]' <<<"$terminals" 2>/dev/null || true)
    note_activity_source "$(jq -r '[.terminals[] | select(.state == "live" and (.address | contains("/") | not))] | length' <<<"$terminals" 2>/dev/null || printf 0) hc terminal(s)"
  else
    note_activity_source "no hc core"
  fi

  if [[ ! -d /proc ]]; then
    note_activity_source "process cwds UNAVAILABLE (no /proc)"
    return 0
  fi
  note_activity_source "process cwds"
  for proc in /proc/[0-9]*; do
    pid=${proc#/proc/}
    if [[ $pid == "$$" || $pid == "$PPID" ]]; then
      continue
    fi
    cwd=$(readlink -- "$proc/cwd" 2>/dev/null) || continue
    [[ -n $cwd ]] || continue
    comm=$(cat -- "$proc/comm" 2>/dev/null) || comm="process"
    ACTIVE_DIRS+=("$cwd")
    ACTIVE_LABELS+=("$comm (pid $pid)")
  done
}

activity_for() {
  local target=$1 slug=$2 i dir label seen="" hits="" window tab workspace space
  for i in "${!ACTIVE_DIRS[@]}"; do
    dir=${ACTIVE_DIRS[$i]}
    [[ $dir == "$target" || $dir == "$target"/* ]] || continue
    label=${ACTIVE_LABELS[$i]}
    if [[ $seen == *"|$label|"* ]]; then
      continue
    fi
    seen="$seen|$label|"
    hits=${hits:+$hits, }$label
  done
  for window in ${TMUX_WINDOWS[@]+"${TMUX_WINDOWS[@]}"}; do
    if [[ $window == "$slug" ]]; then
      hits=${hits:+$hits, }"tmux window '$slug'"
      break
    fi
  done
  for tab in ${HERDR_TABS[@]+"${HERDR_TABS[@]}"}; do
    if [[ $tab == "$slug" ]]; then
      hits=${hits:+$hits, }"herdr tab '$slug'"
      break
    fi
  done
  for workspace in ${HERDR_WORKSPACES[@]+"${HERDR_WORKSPACES[@]}"}; do
    if [[ $workspace == "$slug" ]]; then
      hits=${hits:+$hits, }"herdr workspace '$slug'"
      break
    fi
  done
  for tab in ${HC_TABS[@]+"${HC_TABS[@]}"}; do
    if [[ $tab == "$slug" ]]; then
      hits=${hits:+$hits, }"hc tab '$slug'"
      break
    fi
  done
  for space in ${HC_SPACES[@]+"${HC_SPACES[@]}"}; do
    if [[ $space == "$slug" ]]; then
      hits=${hits:+$hits, }"hc space '$slug'"
      break
    fi
  done
  printf '%s' "$hits"
}

dir_bytes() {
  local path=$1 out
  out=$(du -sx --block-size=1 -- "$path" 2>/dev/null | awk 'NR==1{print $1}') || out=""
  if [[ -z $out ]]; then
    out=$(du -skx -- "$path" 2>/dev/null | awk 'NR==1{print $1 * 1024}') || out=""
  fi
  printf '%s' "${out:-0}"
}

human_bytes() {
  awk -v bytes="$1" 'BEGIN {
    split("B KiB MiB GiB TiB", unit, " ")
    i = 1
    while (bytes >= 1024 && i < 5) { bytes /= 1024; i++ }
    if (i == 1) { printf "%d %s", bytes, unit[i] } else { printf "%.1f %s", bytes, unit[i] }
  }'
}

merged_pr_for() {
  local branch=$1
  ((PR_EVIDENCE)) || return 1
  gh pr list --repo "$GH_REPO" --head "$branch" --state merged \
    --limit 1 --json number --jq '.[0].number // empty' 2>/dev/null
}

declare -a WT_PATHS=() WT_HEADS=() WT_BRANCHES=() WT_FLAGS=()

record_worktree() {
  [[ -n $wt_path ]] || return 0
  WT_PATHS+=("$wt_path")
  WT_HEADS+=("$wt_head")
  WT_BRANCHES+=("$wt_branch")
  WT_FLAGS+=("$wt_flags")
  wt_path=""
  wt_head=""
  wt_branch=""
  wt_flags=""
}

read_worktrees() {
  local line
  WT_PATHS=()
  WT_HEADS=()
  WT_BRANCHES=()
  WT_FLAGS=()
  wt_path=""
  wt_head=""
  wt_branch=""
  wt_flags=""
  while IFS= read -r -d '' line; do
    case $line in
      "worktree "*)
        record_worktree
        wt_path=${line#worktree }
        ;;
      "HEAD "*) wt_head=${line#HEAD } ;;
      "branch "*) wt_branch=${line#branch } ;;
      bare | detached | "locked"* | "prunable"*) wt_flags="$wt_flags ${line%% *}" ;;
      *) ;;
    esac
  done < <(git -C "$BARE_DIR" worktree list --porcelain -z)
  record_worktree
}

has_flag() {
  [[ " $1 " == *" $2 "* ]]
}

VERDICT=""
REASON=""
BRANCH_SHA=""

worktree_index_of() {
  local target=$1 i
  for i in "${!WT_PATHS[@]}"; do
    if [[ ${WT_PATHS[$i]} == "$target" ]]; then
      printf '%s' "$i"
      return 0
    fi
  done
  return 1
}

commit_is_empty() {
  local sha=$1 parent tree parent_tree
  parent=$(git -C "$BARE_DIR" rev-parse --verify --quiet "$sha^1" 2>/dev/null) || return 1
  [[ -n $parent ]] || return 1
  tree=$(git -C "$BARE_DIR" rev-parse "$sha^{tree}")
  parent_tree=$(git -C "$BARE_DIR" rev-parse "$parent^{tree}")
  [[ $tree == "$parent_tree" ]]
}

classify() {
  local path=$1 head=$2 branch=$3 flags=$4
  local real slug dirty landed unique applied ahead empty sha activity pr
  VERDICT=""
  REASON=""
  BRANCH_SHA=""

  if has_flag "$flags" bare; then
    VERDICT=keep
    REASON="bare repository"
    return
  fi

  real=$(abspath "$path" 2>/dev/null || printf '%s' "$path")

  if [[ -n $CURRENT_WT && $real == "$CURRENT_WT" ]]; then
    VERDICT=keep
    REASON="current worktree"
    return
  fi

  if [[ ! -d $real ]]; then
    VERDICT=skip
    REASON="directory is missing (stale worktree entry)"
    return
  fi

  if [[ $real != "$path" ]]; then
    VERDICT=skip
    REASON="registered path resolves elsewhere via a symlink"
    return
  fi

  if [[ $real != "$GARDEN"/* ]]; then
    VERDICT=skip
    REASON="outside the garden root"
    return
  fi

  if [[ $(dirname "$real") != "$GARDEN" ]]; then
    VERDICT=skip
    REASON="agent-managed nested worktree, not a sibling of $PRIMARY_BRANCH/"
    return
  fi

  slug=$(basename "$real")
  if is_protected_name "$slug" || is_protected_name "${branch#refs/heads/}"; then
    VERDICT=keep
    if [[ $slug == "$PRIMARY_BRANCH" || $branch == "refs/heads/$PRIMARY_BRANCH" ]]; then
      REASON="primary worktree ($PRIMARY_BRANCH)"
    else
      REASON="default-branch worktree — never reaped, whatever --primary says"
    fi
    return
  fi

  if has_flag "$flags" locked; then
    VERDICT=skip
    REASON="locked"
    return
  fi

  if [[ -z $branch ]] || has_flag "$flags" detached; then
    VERDICT=skip
    REASON="detached HEAD"
    return
  fi

  if ! BRANCH_SHA=$(git -C "$BARE_DIR" rev-parse --verify --quiet "${branch}^{commit}" 2>/dev/null); then
    VERDICT=skip
    REASON="branch ref does not resolve: $branch"
    return
  fi

  if [[ -n $head && $BRANCH_SHA != "$head" ]]; then
    VERDICT=skip
    REASON="HEAD ${head:0:8} differs from branch tip ${BRANCH_SHA:0:8} — ambiguous"
    return
  fi

  if ! dirty=$(git -C "$real" status --porcelain --untracked-files=normal 2>/dev/null); then
    VERDICT=skip
    REASON="could not read git status"
    return
  fi

  if [[ -n $dirty ]]; then
    VERDICT=skip
    REASON="$(wc -l <<<"$dirty") uncommitted or untracked change(s)"
    return
  fi

  if ! landed=$(git -C "$BARE_DIR" cherry "$PRIMARY_SHA" "$BRANCH_SHA" 2>/dev/null); then
    VERDICT=skip
    REASON="could not compare $branch against $PRIMARY_REF"
    return
  fi

  ahead=0
  empty=0
  for sha in $(awk '/^\+/ {print $2}' <<<"$landed"); do
    if commit_is_empty "$sha"; then
      empty=$((empty + 1))
    else
      ahead=$((ahead + 1))
    fi
  done

  if [[ $ahead -gt 0 ]]; then
    VERDICT=skip
    REASON="not landed on $PRIMARY_REF ($ahead commit(s) with no upstream equivalent)"
    if [[ $empty -gt 0 ]]; then
      REASON="$REASON plus $empty empty"
    fi
    return
  fi

  if [[ $empty -gt 0 ]] && ((STRICT_COMMITS)); then
    VERDICT=skip
    REASON="$empty empty commit(s) missing from $PRIMARY_REF — held back by --strict-commits"
    return
  fi

  applied=$(grep -c '^-' <<<"$landed" || true)
  if [[ $applied -gt 0 ]]; then
    unique="patch-equivalent, $applied commit(s) already upstream"
  else
    unique="no unique commits"
  fi
  if [[ $empty -gt 0 ]]; then
    unique="$unique, $empty empty commit(s) ignored"
  fi

  activity=$(activity_for "$real" "$slug")
  if [[ -n $activity ]]; then
    VERDICT=skip
    REASON="in use by $activity"
    return
  fi

  pr=$(merged_pr_for "${branch#refs/heads/}" || printf '')
  if [[ -n $pr ]]; then
    REASON="merged via PR #$pr ($unique)"
  else
    REASON="$unique"
  fi
  VERDICT=reap
}

display_name() {
  local path=$1
  if [[ $(dirname "$path") == "$GARDEN" ]]; then
    basename "$path"
  elif [[ $path == "$GARDEN"/* ]]; then
    printf '%s' "${path#"$GARDEN"/}"
  else
    printf '%s' "$path"
  fi
}

collect_activity
read_worktrees

declare -a REAP_PATHS=() REAP_BRANCHES=() REAP_BYTES=()
declare -a REAP_ROWS=() KEEP_ROWS=() SKIP_ROWS=()
TOTAL_BYTES=0
STALE_ENTRIES=0

for i in "${!WT_PATHS[@]}"; do
  path=${WT_PATHS[$i]}
  branch=${WT_BRANCHES[$i]}
  classify "$path" "${WT_HEADS[$i]}" "$branch" "${WT_FLAGS[$i]}"

  name=$(display_name "$path")
  slug=$(basename "$path")
  short_branch=${branch#refs/heads/}
  if [[ -n $short_branch && $short_branch != "$slug" ]]; then
    name="$name [$short_branch]"
  fi

  size="-"
  if [[ $VERDICT == reap ]]; then
    bytes=$(dir_bytes "$path")
    size=$(human_bytes "$bytes")
    TOTAL_BYTES=$((TOTAL_BYTES + bytes))
    REAP_PATHS+=("$path")
    REAP_BRANCHES+=("$branch")
    REAP_BYTES+=("$bytes")
    REAP_ROWS+=("$bytes|$name|$size|$REASON")
  elif ((ALL_SIZES)) && [[ -d $path ]]; then
    size=$(human_bytes "$(dir_bytes "$path")")
  fi

  case $VERDICT in
    keep) KEEP_ROWS+=("$name|$size|$REASON") ;;
    skip)
      if [[ $REASON == "directory is missing"* ]]; then
        STALE_ENTRIES=$((STALE_ENTRIES + 1))
      fi
      SKIP_ROWS+=("$name|$size|$REASON")
      ;;
  esac
done

print_row() {
  printf '  %-6s %-56s %10s  %s\n' "$1" "$2" "$3" "$4"
}

print_rows() {
  local verdict=$1 row name size reason
  shift
  for row in "$@"; do
    IFS='|' read -r name size reason <<<"$row"
    print_row "$verdict" "$name" "$size" "$reason"
  done
}

printf 'Worktree reaper — %s\n' "$GARDEN"
printf '  primary      %s @ %s (%s, %sd old)\n' \
  "$PRIMARY_REF" "${PRIMARY_SHA:0:8}" "$PRIMARY_DATE" "$PRIMARY_AGE_DAYS"
printf '  worktrees    %s\n' "${#WT_PATHS[@]}"
printf '  pr evidence  %s\n' "$PR_EVIDENCE_NOTE"
printf '  in-use scan  %s\n' "$ACTIVITY_NOTE"
if ((APPLY)); then
  printf '  mode         apply\n\n'
else
  printf '  mode         dry run\n\n'
fi

if ((${#REAP_ROWS[@]} > 0)); then
  while IFS='|' read -r bytes name size reason; do
    print_row reap "$name" "$size" "$reason"
  done < <(printf '%s\n' "${REAP_ROWS[@]}" | sort -t'|' -k1,1rn)
fi
print_rows keep ${KEEP_ROWS[@]+"${KEEP_ROWS[@]}"}
print_rows skip ${SKIP_ROWS[@]+"${SKIP_ROWS[@]}"}

printf '\n  %s reap, %s keep, %s skip — %s reclaimable\n\n' \
  "${#REAP_ROWS[@]}" "${#KEEP_ROWS[@]}" "${#SKIP_ROWS[@]}" "$(human_bytes "$TOTAL_BYTES")"

cat <<EOF
Git objects live once in .bare/ and are shared by every worktree, so removing a
worktree reclaims its checked-out files only — node_modules, build output,
caches, and other ignored or untracked files. History is never at stake. Sizes
come from du -sx on the worktree directory and stay on one filesystem.
EOF

if ((STALE_ENTRIES > 0)); then
  printf '\n%s worktree entr(ies) point at a missing directory. They are pruned only\nafter a successful removal under --apply.\n' "$STALE_ENTRIES"
fi

if ((PRIMARY_AGE_DAYS > 1)) && ((!DO_FETCH)); then
  printf '\n%s is %s days old; re-run with --fetch so the landed check sees\nrecent merges.\n' "$PRIMARY_REF" "$PRIMARY_AGE_DAYS"
fi

if ((!APPLY)); then
  if ((${#REAP_ROWS[@]} > 0)); then
    fetch_hint=""
    if ((DO_FETCH)); then
      fetch_hint=" --fetch"
    fi
    printf '\nDry run — nothing was touched. To remove the %s worktree(s) above:\n  %s%s --apply\n' \
      "${#REAP_ROWS[@]}" "$0" "$fetch_hint"
  fi
  exit 0
fi

if ((${#REAP_PATHS[@]} == 0)); then
  printf '\nNothing to remove.\n'
  exit 0
fi

printf '\nRemove %s worktree(s) and reclaim %s? Type y to confirm: ' \
  "${#REAP_PATHS[@]}" "$(human_bytes "$TOTAL_BYTES")"
read -r answer || answer=""
case $answer in
  y | Y | yes | Yes) ;;
  *) die "aborted at the confirmation prompt" ;;
esac

printf '\n'
REMOVED=0
FAILED=0
RECLAIMED=0
declare -a KEPT_BRANCHES=()

collect_activity
read_worktrees

for i in "${!REAP_PATHS[@]}"; do
  path=${REAP_PATHS[$i]}
  branch=${REAP_BRANCHES[$i]}
  name=$(display_name "$path")

  if ! fresh=$(worktree_index_of "$path"); then
    printf '  skipped %-56s no longer a registered worktree\n' "$name"
    FAILED=$((FAILED + 1))
    continue
  fi

  classify "$path" "${WT_HEADS[$fresh]}" "${WT_BRANCHES[$fresh]}" "${WT_FLAGS[$fresh]}"
  if [[ $VERDICT != reap ]]; then
    printf '  skipped %-56s %s\n' "$name" "$REASON"
    FAILED=$((FAILED + 1))
    continue
  fi

  if git -C "$GIT_HOST_DIR" worktree remove -- "$path"; then
    printf '  removed %-56s %s\n' "$name" "$(human_bytes "${REAP_BYTES[$i]}")"
    REMOVED=$((REMOVED + 1))
    RECLAIMED=$((RECLAIMED + REAP_BYTES[i]))
    if [[ -n $branch ]]; then
      KEPT_BRANCHES+=("${branch#refs/heads/}")
    fi
  else
    printf '  refused %-56s git worktree remove declined it\n' "$name"
    FAILED=$((FAILED + 1))
  fi
done

if ((REMOVED > 0)); then
  git -C "$GIT_HOST_DIR" worktree prune
  printf '\nPruned stale worktree metadata.\n'
fi

printf '\nRemoved %s worktree(s), reclaimed %s.\n' "$REMOVED" "$(human_bytes "$RECLAIMED")"

if ((${#KEPT_BRANCHES[@]} > 0)); then
  printf '\nBranches were kept. Delete them yourself if you want them gone:\n'
  for branch in "${KEPT_BRANCHES[@]}"; do
    printf '  git -C %s branch -d %s\n' "$GIT_HOST_DIR" "$branch"
  done
fi

if ((FAILED > 0)); then
  printf '\n%s candidate(s) were left in place.\n' "$FAILED"
  exit 2
fi
