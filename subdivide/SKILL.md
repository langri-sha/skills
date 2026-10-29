---
name: subdivide
description: >-
  Branch off new work mid-conversation. Takes a freeform prompt, creates a
  GitHub issue from it, optionally sets up a worktree and development session
  with a new agent fully briefed on the task. Use when new ideas or subtasks
  emerge during a session and you want to spin them off without losing your
  place.
metadata:
  author: langri-sha
  version: '1.1.0'
  argument-hint: '<prompt describing the work> [lane]'
---

# Subdivide

Orchestrate branching off new work mid-conversation: file an issue with `gh`,
then chain `/create-worktree` and `/create-session` into a single flow.

## Arguments

| Argument | Required | Description                                    |
| -------- | -------- | ---------------------------------------------- |
| `prompt` | yes      | Freeform description of the work to branch off |
| `lane`   | no       | tmux session lane (see `/create-session`)      |

## Workflow

### 1. Parse the Prompt

From the user's freeform prompt, infer:

- **Issue title**: a concise summary (under 70 characters)
- **Issue body**: under 100 words, without headings: the problem, why it
  matters, and when it's done
- **Labels**: infer from context, choosing only labels the repository has
  (`gh label list --limit 1000`), since `gh` refuses any other

If the prompt is too vague to infer a clear title or body, ask the user to
clarify before proceeding.

### 2. Create the Issue

File it on the current repository, with the body in a file outside it:

```bash
gh issue create --title "<title>" --body-file <body file> --label <label>
```

If the repository's or the user's instructions name a project board for new
issues, add the issue to it with `gh project item-add` and set the fields they
ask for. Without the `project` scope only that step fails: report it and carry
on.

Capture the resulting:

- `ISSUE_NUMBER` (e.g. `642`)
- `ISSUE_URL` (e.g. `https://github.com/<owner>/<repo>/issues/642`)
- `ISSUE_TITLE`
- `REPO` — the `owner/repo` it was filed against
  (`gh repo view --json nameWithOwner -q .nameWithOwner`)

### 3. Ask Whether to Start Immediately

Ask the user:

> Issue created: **<REPO>#<NUMBER>**
>
> Start working on it now? (creates worktree + development session with a new
> agent)

If the user says **no**, skip to step 6 and return just the issue URL.

### 4. Create the Worktree

Generate the worktree slug from the issue number and title:

```
<ISSUE_NUMBER>-<slugified-title>
```

Examples:

- Issue #642 "Add PDF export" -> `642-add-pdf-export`
- Issue #650 "Fix auth redirect loop" -> `650-fix-auth-redirect-loop`

Invoke `/create-worktree` with this slug and capture the worktree path it
reports (`WORKTREE_PATH`).

### 5. Launch the Development Session

Build a prompt for the new agent that includes full context:

```
Implement issue #<ISSUE_NUMBER>. Read it with: gh issue view <ISSUE_NUMBER>.

<original user prompt>
```

Invoke `/create-session` with:

- **backend**: use the caller context, or the backend the user explicitly
  requested. Resolve ambiguous context through `/create-session`.
- **tmux lane**: for tmux, pass the lane the user asked for; `proposals` for
  proposal or design-doc work; otherwise `dev`. Pass it explicitly rather than
  inheriting the current conversation's lane. For Herdr, omit the lane and use
  the new worktree's native workspace; forward an explicit workspace request. If
  the user supplied a lane with Herdr, clarify the destination before launch.
- **assistant**: `claude`
- **prompt**: the constructed prompt above

This creates a tmux window in the chosen lane or opens the worktree's Herdr
workspace, with Claude on the left pane (fully briefed) and critique on the
right.

### 6. Output Summary

#### If started immediately

```
Subdivided!

  Issue:    <REPO>#<NUMBER> — <TITLE>
  Worktree: <WORKTREE_PATH>
  Branch:   <slug>
  Session:  <backend> window/tab "<slug>" in <lane-or-workspace> with claude + critique

You can continue working here. The new agent is running next door.
```

#### If deferred

```
Subdivided!

  Issue: <REPO>#<NUMBER> — <TITLE>

Run /create-worktree <slug> when you're ready to start.
```

## Edge Cases

### Session Creation Fails

`/create-session` creates missing tmux lanes or opens the Herdr worktree
workspace on demand. tmux can start detached when explicitly selected; Herdr
requires a validated managed caller pane. If session creation fails, report the
error and any partially created session IDs — the issue and worktree are still
created successfully.

### Issue Creation Fails

If `gh issue create` fails (e.g. missing `gh` scopes), stop and report the
error. Do not proceed to worktree creation.

### Worktree Slug Already Exists

`/create-worktree` reuses an existing worktree with that slug. Say so, since it
may hold other work.
