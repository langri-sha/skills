---
name: create-pr
description:
  Use this skill when the user says "create a PR", "open a pull request", or
  wants to create a GitHub pull request. Analyzes git changes, reads the PR
  template, generates descriptions, and handles stacked branches.
---

# Create PR

## Overview

This skill automates GitHub pull request creation by analyzing git history,
changes, and commit messages to generate comprehensive PR descriptions that
follow the repository's GitHub PR template. It handles complex scenarios
including stacked branches (Git Town), detached HEAD states, and custom base
branches.

## When to Use This Skill

Invoke this skill when the user requests:

- "Create a PR"
- "Open a pull request"
- "Make a PR for this branch"
- "Create a pull request with description"
- Any variation requesting GitHub PR creation

## Core Workflow

### Container-Use Environment Detection (Pre-Step)

**CRITICAL: Before proceeding with standard workflow, check if working with a
container-use environment.**

Container-use environments store changes in remote refs like
`container-use/<env-id>` without requiring local checkout. When creating PRs
from these environments:

**Detection:**

```bash
# Check if dealing with a container-use environment
git branch -a | grep "remotes/container-use/"
```

**If container-use environment detected:**

1. **NEVER perform git checkout** - This changes the user's working directory
2. **Identify the environment ref:**
   - Look for recent environment (e.g., `container-use/well-raptor`)
   - User will typically mention the environment name or it will be in context
3. **Determine base branch:**
   - Check git status or ask user what branch the environment was created from
   - Common pattern: Current working branch is the base branch
4. **Push directly without checkout:**

   ```bash
   # Check if the target branch already exists to avoid accidental overwrites
   if git ls-remote --exit-code --heads origin <proper-branch-name>; then
       echo "Branch <proper-branch-name> already exists. Please choose a different name."
       exit 1
   fi

   # Push the container-use ref to a new properly-named branch
   git push origin container-use/<env-id>:refs/heads/<proper-branch-name>
   ```

   Example:

   ```bash
   git push origin container-use/well-raptor:refs/heads/chore/remove-test-scripts
   ```

5. **Analyze changes using the remote ref:**

   ```bash
   # Get commits
   git log <base-branch>..container-use/<env-id>

   # Get file changes
   git diff --name-status <base-branch>...container-use/<env-id>
   ```

6. **Create PR from the newly pushed branch:**
   ```bash
   gh pr create --base <base-branch> --head <proper-branch-name> --title "<title>" --body "<description>"
   ```

**Why avoid checkout with container-use:**

- User's working directory may have uncommitted changes
- Container-use environments are isolated from the local workspace
- Checking out would disrupt the user's current work
- The environment changes are already available as remote refs

**Branch naming for container-use PRs:**

- Use descriptive names based on the work done
- Common prefixes: `feature/`, `fix/`, `chore/`, `refactor/`
- Example: If removing test scripts, use `chore/remove-test-scripts`

**If NOT a container-use environment:**

- Proceed with standard workflow (Steps 1-6 below)

### Step 1: Determine the Base Branch

The base branch is the target branch the PR will merge into. Determine it using
this priority order:

1. **User-specified base branch** (highest priority)
   - If user says "create a PR to develop", use `develop`
   - If user mentions "stacked branch" or "parent branch", ask for clarification
     if needed

2. **Git Town parent branch** (if available)
   - Run `scripts/detect_stacked_branch.py` to check if the current branch is
     stacked
   - If it returns a parent branch, use that as the base branch
   - Exit code 0 = stacked (prints parent branch name)
   - Exit code 1 = not stacked
   - Exit code 2 = Git Town not available

3. **Default branch** (fallback)
   - Use `main` or `master` (detect with `git remote show origin`)

**Example execution:**

```bash
# Check if stacked
parent=$(python3 scripts/detect_stacked_branch.py 2>/dev/null)
if [ $? -eq 0 ]; then
    base_branch="$parent"
else
    base_branch="main"  # or detect default
fi
```

### Step 1.5: Verify Workspace State

**Check for uncommitted changes:**

Before proceeding, ensure the user's latest work is included.

```bash
# Check status
git status --porcelain
```

- **If output is not empty:**
  - Ask the user: "You have uncommitted changes. Should I commit them, stash
    them, or include them in the PR?"
  - **Commit:** Generate a commit message and run `git commit`.
  - **Stash:** Run `git stash` (warn user they won't be in the PR).
  - **Ignore:** Proceed (changes won't be in PR).

### Step 2: Handle Branch Name

**If on a named branch:**

- Get current branch: `git rev-parse --abbrev-ref HEAD`
- Use this branch name for the PR

**If on detached HEAD:**

- Detached HEAD means not on any branch (shows "HEAD" instead of branch name)
- Generate a meaningful branch name:
  `python3 scripts/generate_branch_name.py [base_branch]`
- Create the branch: `git checkout -b <generated-name>`

**Convert branch name to PR title:**

- Remove common prefixes: `feature/`, `fix/`, `bugfix/`, `hotfix/`, `chore/`
- Dasherize: replace underscores/slashes with dashes
- Capitalize words for title
- Example: `feature/user-authentication` → "User Authentication"

### Step 3: Analyze Changes

Build a comprehensive understanding by analyzing:

**IMPORTANT:** Always fetch and compare against the **remote** base branch
(`origin/<base-branch>`) to avoid stale local refs. Local `main` may be behind
`origin/main`, causing diffs to include already-merged commits.

```bash
# Always fetch first
git fetch origin <base-branch>
```

**1. Commit history:**

```bash
# Get all commits between remote base branch and HEAD
git log origin/<base-branch>..HEAD --pretty=format:"%h %s%n%b"
```

Extract:

- Commit subjects (summaries)
- Commit bodies (detailed context)
- Overall patterns (bug fixes, features, refactoring, tests, docs)

**2. Code changes:**

**Handle Context Limits:** If the diff is too large, it may exceed context
windows.

1. **Check size first:**

   ```bash
   git diff --stat origin/<base-branch>...HEAD
   ```

2. **If manageable (e.g., < 500 lines):**

   ```bash
   git diff origin/<base-branch>...HEAD
   ```

3. **If large:**
   - Prioritize source code (`src/`, `lib/`) over assets/lockfiles.
   - Read key files individually.
   - Rely more on commit messages for the summary.

4. **Get file list:**
   ```bash
   git diff --name-status origin/<base-branch>...HEAD
   ```

Extract:

- What files were modified, added, or deleted
- Scope of changes (frontend, backend, tests, docs)
- Key functionality affected

**3. Synthesis:** Combine commit messages and diff analysis to understand:

- **What** changed (specific modifications)
- **Why** it changed (purpose and reasoning)
- **How** to test it (validation approach)

### Step 3.5: Metadata Analysis

Infer labels and reviewers to make the PR complete.

**Labels:**

- `fix: ...` commits → `bug` label
- `feat: ...` commits → `enhancement` label
- `docs: ...` commits → `documentation` label

**Reviewers:**

- If user says "ask @dave to review" → add reviewer `dave`
- If `CODEOWNERS` exists, note relevant owners.

### Step 4: Read and Fill GitHub PR Template

**Locate the template:** Check these locations in order:

1. `.github/PULL_REQUEST_TEMPLATE.md`
2. `.github/pull_request_template.md`
3. `PULL_REQUEST_TEMPLATE.md` (repository root)
4. `docs/PULL_REQUEST_TEMPLATE.md`

If multiple exist, prefer `.github/` directory.

**Parse the template:**

- Templates typically have sections with markdown headers
- Common sections: `## Summary`, `## Changes`, `## Test Plan`, `## Screenshots`
- May include checkboxes: `- [ ] Tests added`

**Fill each section:**

1. **Summary/Overview:**
   - 1-3 sentence high-level description
   - Focus on "what" and "why"
   - Based on overall pattern of commits
   - Example: "This PR adds JWT-based authentication to secure API endpoints and
     protect user data."

2. **Changes/Details:**
   - Bullet points of specific changes
   - Derived from commits and diff analysis
   - Group related changes together
   - Example:
     ```
     - Added JWT middleware for token validation
     - Created `/api/login` and `/api/refresh` endpoints
     - Updated User model with password hashing
     - Added authentication tests
     ```

3. **Test Plan:**
   - How to verify the changes work
   - Include both automated tests and manual testing steps
   - Example:
     ```
     - Run `npm test` to verify all tests pass
     - Test login flow: POST to `/api/login` with credentials
     - Verify protected routes return 401 when unauthenticated
     - Confirm token refresh works with valid refresh token
     ```

4. **Additional Sections:**
   - Fill any other template sections based on context
   - For screenshots: mention if applicable or mark as N/A
   - For breaking changes: identify from commits/diff

**Checkboxes:**

- Leave all checkboxes unchecked in the PR description
- Reviewers and authors will check them during review
- Don't assume completion of checklist items

### Step 5: Incorporate User Input

User input always takes precedence over automated generation:

**Types of user input:**

1. **Explicit title:**
   - User: "Title this 'Add dashboard feature'"
   - Use verbatim: `--title "Add dashboard feature"`

2. **Explicit description content:**
   - User: "Mention this fixes issue #123"
   - Add `Fixes #123` to appropriate section (GitHub auto-links issues)

3. **Explicit base branch:**
   - User: "Target the develop branch"
   - Override detection: `--base develop`

4. **Additional context:**
   - User: "Note this is for Q1 milestone"
   - Add to Summary or Notes section

5. **No user input:**
   - Use automated analysis from Steps 1-4
   - Generate best possible PR based on available information

**Priority order:**

```
User input > Git Town config > Branch/commit analysis > Defaults
```

### Step 6: Create the Pull Request

**Prerequisites:**

1. **Check for existing PR:**

   ```bash
   gh pr list --head <branch-name> --json url
   ```

   - If a PR exists, return the URL and ask if the user wants to update it using
     `gh pr edit`.

2. **Ensure branch is up-to-date:**
   - Base was already fetched in Step 3
   - If behind, suggest: `git rebase origin/<base-branch>`

3. **Interactive Review:**
   - **CRITICAL:** Before creating, show the generated **Title** and **Body** to
     the user.
   - Ask: "Here is the PR description. Does this look good?"

**Push and Create:**

```bash
# Push branch
git push -u origin <branch-name>

# Create PR with metadata
gh pr create \
  --base <base-branch> \
  --title "<title>" \
  --label "<inferred-labels>" \
  --reviewer "<inferred-reviewers>" \
  --body "$(cat <<'EOF'
<filled-pr-template>
EOF
)"
```

**Return to user:**

- The PR URL from `gh pr create` output
- Confirmation message
- Example: "Pull request created: https://github.com/user/repo/pull/123"

## Stacked Branches

Stacked branches are a development pattern where features are split into
multiple dependent PRs, creating a "stack":

```
main
  └─ feature/user-model (PR #1)
      └─ feature/user-auth (PR #2)
          └─ feature/user-profile (PR #3)
```

**Detection:**

- Use `scripts/detect_stacked_branch.py` to check Git Town configuration
- Git Town stores parent relationships in git config
- User may explicitly mention "stacked branch"

**Creating stacked PRs:**

1. Base branch is the parent branch, not main
2. Title should indicate it's part of a series if appropriate
3. Description should mention the dependency: "This PR builds on #123 and
   adds..."

## Helper Scripts

### `scripts/detect_stacked_branch.py`

Detects if the current branch is stacked using Git Town.

**Usage:**

```bash
python3 scripts/detect_stacked_branch.py
```

**Exit codes:**

- 0: Branch is stacked (prints parent branch name to stdout)
- 1: Branch is not stacked
- 2: Git Town not available or not configured

**Example:**

```bash
parent=$(python3 scripts/detect_stacked_branch.py 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "Stacked branch with parent: $parent"
fi
```

### `scripts/generate_branch_name.py`

Generates a meaningful branch name from git commits and changes. Useful when on
detached HEAD.

**Usage:**

```bash
python3 scripts/generate_branch_name.py [base_branch]
```

**Arguments:**

- `base_branch`: Optional base branch to compare against (default: main)

**Output:**

- Dasherized branch name based on commit analysis
- Example: `user-authentication-jwt`

**Example:**

```bash
# Generate branch name comparing to main
branch_name=$(python3 scripts/generate_branch_name.py main)
git checkout -b "$branch_name"
```

## Reference Documentation

For detailed information on specific aspects of PR creation, consult:

**`references/pr-workflow.md`:**

- In-depth explanation of each workflow step
- Stacked branches deep dive
- Git Town integration details
- Troubleshooting guide
- Best practices for PR titles and descriptions

Load this reference when:

- Encountering complex scenarios
- Need detailed Git Town information
- Debugging issues
- User asks about stacked branches or specific workflow details

## Examples

### Example 1: Simple PR Creation

**User request:** "Create a PR"

**Execution:**

1. Detect base branch: `main` (no Git Town parent, not user-specified)
2. Get current branch: `feature/add-login`
3. Generate title: "Add Login"
4. Analyze commits between `main..HEAD`
5. Read `.github/PULL_REQUEST_TEMPLATE.md`
6. Fill template based on commits showing login form, validation, API
   integration
7. Create PR:
   `gh pr create --base main --title "Add Login" --body "<filled-template>"`

### Example 2: Stacked Branch PR

**User request:** "Create a stacked PR, this builds on the user-model branch"

**Execution:**

1. User specified parent: `user-model` (highest priority)
2. Base branch: `user-model`
3. Current branch: `feature/user-auth`
4. Generate title: "User Auth"
5. Analyze commits between `user-model..HEAD`
6. Fill template, add note: "This PR builds on #45 (user-model) and adds
   authentication..."
7. Create PR:
   `gh pr create --base user-model --title "User Auth" --body "<filled-template>"`

### Example 3: Detached HEAD

**User request:** "Make a PR"

**Execution:**

1. Detect detached HEAD: `git rev-parse --abbrev-ref HEAD` returns "HEAD"
2. Generate branch name: `python3 scripts/generate_branch_name.py` →
   "dashboard-metrics"
3. Create branch: `git checkout -b dashboard-metrics`
4. Continue with normal PR creation workflow
5. Title: "Dashboard Metrics"

### Example 4: Custom Title and Context

**User request:** "Create a PR titled 'Emergency hotfix for login bug' and
mention this fixes #789"

**Execution:**

1. Use user-provided title verbatim: "Emergency hotfix for login bug"
2. Detect base branch (likely `main`)
3. Analyze commits
4. Fill template, ensure `Fixes #789` is included in description
5. Create PR with custom title and enhanced description

### Example 5: Container-Use Environment

**User request:** "Create a PR from the well-raptor environment"

**Execution:**

1. Check for container-use environments: `git branch -a | grep container-use`
2. Find `remotes/container-use/well-raptor`
3. Determine base branch from context (e.g., `epic-2.2-ai-editor-features`)
4. Analyze changes:
   `git log epic-2.2-ai-editor-features..container-use/well-raptor`
5. Generate appropriate branch name: `chore/remove-test-scripts`
6. Push without checkout:
   `git push origin container-use/well-raptor:refs/heads/chore/remove-test-scripts`
7. Read PR template and fill based on analysis
8. Create PR:
   `gh pr create --base epic-2.2-ai-editor-features --head chore/remove-test-scripts --title "Remove test shell scripts" --body "<filled-template>"`
9. Return PR URL to user

**Key difference:** No `git checkout` command was used, preserving the user's
working directory state.

## Best Practices

1. **Always analyze thoroughly:** Don't rush to create the PR. Spend time
   understanding commits and changes.

2. **Respect user input:** User-provided information always overrides automated
   detection.

3. **Be specific in descriptions:** Vague PRs are hard to review. Include
   concrete details from diff analysis.

4. **Check for edge cases:**
   - Empty diff (no changes)
   - Detached HEAD
   - Missing PR template (create a sensible default structure)
   - Git Town not available

5. **Format consistently:** Follow markdown conventions in PR descriptions for
   readability.

6. **Link issues:** Always include `Fixes #123` or `Closes #123` when mentioned
   or found in commits.

7. **Container-use environments:** Always check for container-use environments
   first. NEVER checkout when working with these environments to preserve the
   user's working state.

## Troubleshooting

**"Not a git repository":**

- Verify current directory is a git repository
- Run `git status` to check

**"No commits between base and HEAD":**

- Verify correct base branch
- Check if all changes are committed
- Confirm you're on the right branch

**"gh: command not found":**

- GitHub CLI is not installed
- Instruct user to install: `brew install gh` (macOS) or visit
  https://cli.github.com

**"Permission denied (push)":**

- Check remote: `git remote -v`
- Verify push access to repository
- Try: `gh auth refresh`

**"Failed to create PR":**

- Ensure branch is pushed: `git push -u origin <branch-name>`
- Check if PR already exists for this branch
- Verify base branch exists on remote
