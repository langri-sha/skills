---
name: subdivide
description: >-
  Branch off new work mid-conversation. Takes a freeform prompt, creates a
  GitHub issue from it, optionally sets up a worktree and tmux session with a
  new agent fully briefed on the task. Use when new ideas or subtasks emerge
  during a session and you want to spin them off without losing your place.
metadata:
  author: langri-sha
  version: '1.1.0'
  argument-hint: '<prompt describing the work> [lane]'
---

# Subdivide

Orchestrate branching off new work mid-conversation by chaining `/create-issue`,
`/create-worktree`, and `/tmux-session` into a single flow.

## Arguments

| Argument | Required | Description                                            |
| -------- | -------- | ------------------------------------------------------ |
| `prompt` | yes      | Freeform description of the work to branch off         |
| `lane`   | no       | Session lane for the tmux window (see `/tmux-session`) |

## Workflow

### 1. Parse the Prompt

From the user's freeform prompt, infer:

- **Issue title**: a concise summary (under 70 characters)
- **Issue body**: structured using the appropriate template from `/create-issue`
  (enhancement, bug, or maintenance)
- **Labels**: infer from context (`enhancement`, `bug`, etc.)

If the prompt is too vague to infer a clear title or body, ask the user to
clarify before proceeding.

### 2. Create the Issue

Invoke `/create-issue` with the inferred title, body, and labels. This handles
label selection, body formatting, project board assignment, and returns the
issue URL and number.

Capture the resulting:

- `ISSUE_NUMBER` (e.g. `642`)
- `ISSUE_URL` (e.g. `https://github.com/<owner>/<repo>/issues/642`)
- `ISSUE_TITLE`
- `REPO` — the `owner/repo` that `/create-issue` resolved and filed against

### 3. Ask Whether to Start Immediately

Use AskUserQuestion to ask:

> Issue created: **<REPO>#<NUMBER>**
>
> Start working on it now? (creates worktree + tmux session with a new agent)

If the user says **no**, skip to step 6 and return just the issue URL.

### 4. Create the Worktree

Generate the worktree slug from the issue number and title:

```
<ISSUE_NUMBER>-<slugified-title>
```

Examples:

- Issue #642 "Add PDF export" -> `642-add-pdf-export`
- Issue #650 "Fix auth redirect loop" -> `650-fix-auth-redirect-loop`

Invoke `/create-worktree` with this slug. This handles branch creation, env file
copying, dependency installation, and directory switching.

Capture the resulting worktree path (`WORKTREE_PATH`).

### 5. Launch tmux Session

Build a prompt for the new agent that includes full context:

```
Implement issue #<ISSUE_NUMBER>. Read it with: gh issue view <ISSUE_NUMBER>.

<original user prompt>
```

Invoke `/tmux-session` with:

- **lane**: the lane the user asked for; `proposals` when the branched-off work
  is clearly proposal or design-doc work; otherwise `dev`. Always pass the lane
  explicitly — never rely on `/tmux-session` inheriting whatever lane this
  conversation happens to run in.
- **assistant**: `claude`
- **prompt**: the constructed prompt above

This creates a new tmux window in the chosen lane with Claude on the left pane
(fully briefed) and critique on the right.

### 6. Output Summary

#### If started immediately

```
Subdivided!

  Issue:    <REPO>#<NUMBER> — <TITLE>
  Worktree: ~/workspace/<repo>/<slug>
  Branch:   <slug>
  tmux:     window "<slug>" in lane "<lane>" with claude + critique

You can continue working here. The new agent is running next door.
```

#### If deferred

```
Subdivided!

  Issue: <REPO>#<NUMBER> — <TITLE>

Run /create-worktree <slug> when you're ready to start.
```

## Edge Cases

### No tmux Session Running

`/tmux-session` creates the target lane (and the tmux server) on demand, so this
only fails when tmux itself is unavailable. If it does fail, report the error —
the issue and worktree are still created successfully.

### Issue Creation Fails

If `/create-issue` fails (e.g. missing `gh` scopes), stop and report the error.
Do not proceed to worktree creation.

### Worktree Slug Already Exists

`/create-worktree` handles this — it will ask the user whether to switch to the
existing worktree or pick a different slug.
