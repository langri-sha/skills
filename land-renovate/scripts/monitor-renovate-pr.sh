#!/usr/bin/env bash
#
# monitor-renovate-pr.sh — watch a single Renovate PR until its checks settle.
#
# Usage:
#   monitor-renovate-pr.sh <pr-number> <repo> <baseline-head-sha-short>
#
# Polls the PR every POLL_INTERVAL seconds (default 45) and prints a status line
# only when the signature changes. A verdict is emitted once:
#   * the head SHA has moved off the baseline (Renovate/the app bot rebased), AND
#   * no checks are pending, AND
#   * the signature is stable across two consecutive polls.
#
# Final line on stdout (the agent consumes this via the Monitor tool):
#   GREEN:     #<n> ready to merge
#   NOT-GREEN: #<n> settled failures=X mergeable=Y state=Z
#
# Optional env:
#   POLL_INTERVAL   seconds between polls (default 45)
#   MAX_POLLS       give up after N polls; 0 = unlimited (default 0). On
#                   exhaustion emits: NOT-GREEN: #<n> timeout failures=X ...
set -euo pipefail

PR="${1:?usage: monitor-renovate-pr.sh <pr-number> <repo> <baseline-head-sha-short>}"
REPO="${2:?repo required (owner/name)}"
BASELINE="${3:?baseline head SHA (short) required}"

INTERVAL="${POLL_INTERVAL:-45}"
MAX_POLLS="${MAX_POLLS:-0}"

# jq: collapse statusCheckRollup into "<ok> <pending> <failures>".
# CheckRun carries status+conclusion; StatusContext carries state.
ROLLUP_JQ='
[ .statusCheckRollup[]
  | if .__typename == "CheckRun"
    then ( .conclusion as $c
         | if .status != "COMPLETED" then "PENDING"
           elif (["FAILURE","CANCELLED","TIMED_OUT","ACTION_REQUIRED","STARTUP_FAILURE"] | index($c)) then "FAILURE"
           else "OK" end )
    else ( if (.state == "PENDING" or .state == "EXPECTED") then "PENDING"
           elif (.state == "FAILURE" or .state == "ERROR") then "FAILURE"
           else "OK" end )
    end
]
| "\([.[]|select(.=="OK")]|length) \([.[]|select(.=="PENDING")]|length) \([.[]|select(.=="FAILURE")]|length)"
'

ts() { date -u +%H:%M:%SZ; }

prev_sig=""
stable=0
polls=0

while true; do
  polls=$((polls + 1))

  if ! json=$(gh pr view "$PR" -R "$REPO" \
      --json headRefOid,mergeable,mergeStateStatus,statusCheckRollup 2>/dev/null \
      | sed -n '/^{/,$p'); then
    printf '%s  #%s  poll-error (will retry)\n' "$(ts)" "$PR"
    sleep "$INTERVAL"
    continue
  fi

  if [ -z "$json" ]; then
    printf '%s  #%s  poll-error: empty/non-JSON gh output (will retry)\n' "$(ts)" "$PR"
    sleep "$INTERVAL"
    continue
  fi

  head=$(jq -r '.headRefOid' <<<"$json")
  mergeable=$(jq -r '.mergeable' <<<"$json")
  state=$(jq -r '.mergeStateStatus' <<<"$json")
  read -r ok pending failures < <(jq -r "$ROLLUP_JQ" <<<"$json")

  rollup="ok=$ok pend=$pending fail=$failures"
  sig="${head:0:9}|$mergeable:$state|$rollup"

  if [ "$sig" != "$prev_sig" ]; then
    printf '%s  #%s  %s\n' "$(ts)" "$PR" "$sig"
  fi

  # "moved" means the head has been rebased off the baseline we started from.
  if [[ "$head" == "$BASELINE"* ]]; then
    moved=0
  else
    moved=1
  fi

  # Settled = rebased AND nothing still running. Require two stable polls.
  if [ "$moved" -eq 1 ] && [ "$pending" -eq 0 ]; then
    if [ "$sig" = "$prev_sig" ]; then
      stable=$((stable + 1))
    else
      stable=1
    fi
  else
    stable=0
  fi

  prev_sig="$sig"

  if [ "$stable" -ge 2 ]; then
    if [ "$failures" -eq 0 ] && [ "$mergeable" = "MERGEABLE" ]; then
      echo "GREEN: #$PR ready to merge"
    else
      echo "NOT-GREEN: #$PR settled failures=$failures mergeable=$mergeable state=$state"
    fi
    exit 0
  fi

  if [ "$MAX_POLLS" -gt 0 ] && [ "$polls" -ge "$MAX_POLLS" ]; then
    echo "NOT-GREEN: #$PR timeout failures=$failures mergeable=$mergeable state=$state"
    exit 0
  fi

  sleep "$INTERVAL"
done
