---
name: agent-browser-hygiene
description: >-
  Runs every browser-automation task in a fresh throwaway profile, created first
  and deleted last, never the user's real Chrome profile. Use alongside
  agent-browser whenever a task drives a website, web app or Electron app:
  navigating, filling forms, clicking, screenshots, scraping, testing a web UI,
  signing in, or working in an admin console.
metadata:
  author: langri-sha
  version: '1.0.0'
---

# Agent Browser Hygiene

Run every browser-automation task in a fresh throwaway profile. Create it as the
first step, delete it as the last. Never point agent-browser at the user's real
Chrome profile.

## Why

A browser profile is a credential store: live Google/SSO session cookies,
tokens, IndexedDB. Reusing the user's real profile risks a profile-lock conflict
with their running Chrome, and hands automation their full authenticated
identity. Leaving a throwaway behind leaves those session cookies on disk after
the task that justified them is over. Fresh-per-task also means a flaky or
half-finished run never poisons the next one with stale state.

## Lifecycle

Pair the create and the delete like `mktemp` / `shred -u`: the profile is born
with the task and dies with it.

```bash
PROF=$(mktemp -d /tmp/ab-profile-XXXXXX)
agent-browser open --headed --profile "$PROF" --session <name> <url>
# ... work ...
agent-browser close --all
rm -rf "$PROF"
```

`--profile` takes a Chrome profile name or a directory path; passing a path is
what makes the profile disposable. Delete it even when the task fails or is
abandoned midway. Do not keep it "in case we need the session again" — if the
task resumes, mint a new profile and sign in again.

## Gotchas

### A running daemon silently ignores --profile

`--profile` and `--headed` are ignored if an agent-browser daemon is already
running. It prints `⚠ --profile, --headed ignored: daemon already running` and
carries on with whatever profile the daemon was started with — which may well be
the user's real one. Fully stop the daemon with `agent-browser close --all`
before opening, then verify it actually stopped before trusting that the fresh
profile is in effect.

### pgrep matches your own check

`pgrep -f agent-browser` matches the shell command doing the checking, producing
endless false positives. Verify the daemon is gone by resolving `/proc/*/exe`
instead:

```bash
for p in /proc/[0-9]*; do
  case "$(readlink "$p/exe" 2>/dev/null)" in
    *agent-browser*) echo "still running: ${p#/proc/}" ;;
  esac
done
```

No output means the daemon is gone.

### Sign-in: hand the keyboard to the human

When the task needs an authenticated session, open the headed window and ask the
user to sign in interactively. Do not automate credential entry — Google in
particular may block automated sign-in with "This browser or app may not be
secure." The interactive session lives only in the throwaway profile and is
destroyed with it.
