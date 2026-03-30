# Pull Request Creation Workflow Reference

This document provides detailed guidance on creating pull requests using the
pr-creator skill.

## Container-Use Environments

### Overview

Container-use environments are isolated development environments that store
changes in special git remote refs (e.g., `container-use/well-raptor`). These
environments keep changes separate from the local working directory.

### Why Special Handling is Needed

**Problem:** Container-use environments maintain their state in remote refs, not
in the local working directory. Checking out these refs would:

- Overwrite the user's current working directory
- Potentially lose uncommitted local changes
- Disrupt ongoing work in the current branch

**Solution:** Work with the remote refs directly without checking them out
locally.

### Detection

Check if you're working with a container-use environment:

```bash
# List all container-use branches
git branch -a | grep "remotes/container-use/"

# Example output:
# remotes/container-use/well-raptor
# remotes/container-use/humorous-falcon
```

**Indicators:**

- User mentions an environment by name (e.g., "create PR from well-raptor")
- Recent conversation involved container-use operations
- Remote refs matching `container-use/*` pattern exist

### Workflow for Container-Use Environments

**Step 1: Identify the environment ref**

```bash
# Find the specific environment
git branch -a | grep "container-use/<env-name>"
```

**Step 2: Determine base branch**

- Ask user or infer from context
- Often the branch that was active when environment was created
- Check git status or recent conversation history

**Step 3: Analyze changes without checkout**

```bash
# View commits
git log <base-branch>..container-use/<env-id> --pretty=format:"%h %s%n%b"

# View file changes
git diff --name-status <base-branch>...container-use/<env-id>

# View full diff
git diff <base-branch>...container-use/<env-id>
```

**Step 4: Generate proper branch name**

- Analyze the changes to determine appropriate name
- Follow conventions: `feature/`, `fix/`, `chore/`, `refactor/`
- Examples:
  - Removing test files: `chore/remove-test-scripts`
  - Adding authentication: `feature/user-authentication`
  - Fixing bug: `fix/login-validation`

**Step 5: Push to new branch without checkout**

```bash
# Push the container-use ref directly to a new branch on origin
git push origin container-use/<env-id>:refs/heads/<proper-branch-name>

# Example:
git push origin container-use/well-raptor:refs/heads/chore/remove-test-scripts
```

**Step 6: Create PR from the new branch**

```bash
gh pr create --base <base-branch> --head <proper-branch-name> --title "<title>" --body "<body>"
```

### Important Rules

1. **NEVER use `git checkout` with container-use refs**
   - ❌ `git checkout container-use/well-raptor`
   - ❌ `git checkout -b new-branch container-use/well-raptor`
   - ✅ `git push origin container-use/well-raptor:refs/heads/new-branch`

2. **Always analyze changes using remote ref syntax**
   - Use `container-use/<env-id>` in git commands
   - No need to be on the branch locally

3. **Preserve user's working directory**
   - User may have uncommitted changes
   - Current branch state should remain unchanged

### Example: Complete Container-Use PR Creation

```bash
# 1. Detect container-use environment
git branch -a | grep "container-use/well-raptor"
# Output: remotes/container-use/well-raptor

# 2. Determine base branch (from context: epic-2.2-ai-editor-features)

# 3. Analyze changes
git log epic-2.2-ai-editor-features..container-use/well-raptor --pretty=format:"%h %s"
# Output:
# f7ac077 Restoring package.json test scripts
# 3c2becd Deleting test-pr-deployments.sh
# 1c447bb Deleting test-portainer-simple.sh
# ...

git diff --name-status epic-2.2-ai-editor-features...container-use/well-raptor
# Output:
# D    test-branch-deployment.sh
# D    test-portainer-api.sh
# ...

# 4. Generate branch name: chore/remove-test-scripts

# 5. Push without checkout
git push origin container-use/well-raptor:refs/heads/chore/remove-test-scripts

# 6. Create PR
gh pr create \
  --base epic-2.2-ai-editor-features \
  --head chore/remove-test-scripts \
  --title "Remove test shell scripts" \
  --body "$(cat <<'EOF'
## Summary
Removes obsolete test shell scripts...
EOF
)"
```

## Core Workflow

### 1. Determine Base Branch

The base branch is the branch that the PR will be merged into. Determining the
correct base branch is critical:

**Standard Branch:**

- Most PRs target `main` or `master`
- Use `git remote show origin` to identify the default branch
- Common default branches: `main`, `master`, `develop`

**Stacked Branch:**

- A stacked branch has a parent branch (other than main/master)
- Stacked branches are used for incremental feature development
- The parent branch becomes the base branch for the PR

**Detection Methods:**

1. **Git Town** (preferred if available):
   - Git Town stores parent branch configuration
   - Use `scripts/detect_stacked_branch.py` to check
   - Command: `git config --get git-town.parent.<branch-name>`
   - Returns the parent branch name if configured

2. **User Input:**
   - User may explicitly specify this is a stacked branch
   - User may provide the parent branch name
   - Always prioritize explicit user input

3. **Fallback:**
   - If no Git Town config and no user input, assume main/master
   - Better to ask the user if uncertain

### 2. Branch Name Handling

**Named Branch:**

- If on a named branch, use it as-is for the branch name
- Dasherize the branch name for the PR title
- Example: `feature/user-auth` → title: "Feature User Auth"

**Detached HEAD:**

- Common when checking out specific commits or tags
- Must create a branch before creating PR
- Use `scripts/generate_branch_name.py` to generate a meaningful name
- The script analyzes commits and changes to suggest a name
- Always create the branch with: `git checkout -b <generated-name>`

**Branch Name to Title Conversion:**

- Remove common prefixes: `feature/`, `fix/`, `bugfix/`, `hotfix/`
- Replace dashes and underscores with spaces
- Capitalize words
- Example: `fix/authentication-bug` → "Authentication Bug"

### 3. Analyze Changes

To build a comprehensive understanding of the changes:

**Git Diff Analysis:**

```bash
# Get the full diff between base branch and HEAD
git diff <base-branch>...HEAD

# For file-level changes
git diff --name-status <base-branch>...HEAD
```

**Commit History Analysis:**

```bash
# Get all commits between base branch and HEAD
git log <base-branch>..HEAD --pretty=format:"%h %s%n%b"

# Get commit subjects only
git log <base-branch>..HEAD --pretty=format:"%s"
```

**What to Extract:**

1. **Files changed:** What files were modified, added, or deleted?
2. **Commit subjects:** High-level summary of changes
3. **Commit bodies:** Detailed context and reasoning
4. **Patterns:** Are these bug fixes, new features, refactoring, tests, docs?
5. **Scope:** What parts of the codebase are affected?

### 4. GitHub PR Template

**Finding the Template:**

GitHub PR templates can be located in several places:

1. `.github/PULL_REQUEST_TEMPLATE.md`
2. `.github/pull_request_template.md`
3. `PULL_REQUEST_TEMPLATE.md` (root)
4. `docs/PULL_REQUEST_TEMPLATE.md`

If multiple templates exist, GitHub typically uses the one in `.github/`
directory.

**Reading the Template:**

- Read the template file from the repository
- The template usually contains sections with headers and checkboxes
- Common sections: Summary, Changes, Test Plan, Screenshots, Notes

**Filling the Template:**

1. **Summary Section:**
   - High-level overview of what changed (1-3 sentences)
   - Focus on the "what" and "why"
   - Example: "This PR adds user authentication using JWT tokens to secure API
     endpoints."

2. **Changes/Details Section:**
   - Bullet points of specific changes
   - Derived from commit messages and diff analysis
   - Be specific but concise
   - Example:
     ```
     - Added JWT middleware for authentication
     - Created login endpoint
     - Updated user model with password hashing
     ```

3. **Test Plan Section:**
   - How to verify the changes work
   - Manual testing steps or automated tests added
   - Example:
     ```
     - Run `npm test` to verify all tests pass
     - Test login flow at `/api/login`
     - Verify protected routes reject unauthenticated requests
     ```

4. **Checkboxes:**
   - Leave unchecked if the template has checkboxes
   - The user or reviewers will check them during review
   - Don't assume completion of checklist items

### 5. User Input Handling

**Types of User Input:**

1. **Explicit Title:**
   - User: "Create PR titled 'Add dashboard feature'"
   - Use the provided title verbatim

2. **Explicit Description:**
   - User: "The description should mention this is for the Q1 milestone"
   - Incorporate into the appropriate template section

3. **Explicit Base Branch:**
   - User: "This PR should target the develop branch"
   - Override any auto-detection with user's specification

4. **Additional Context:**
   - User: "Mention that this fixes issue #123"
   - Add to relevant sections and include in PR body
   - GitHub will auto-link issues with `Fixes #123` syntax

5. **No User Input:**
   - Do your best with available information
   - Analyze git history and changes thoroughly
   - Generate reasonable defaults

**Priority Order:**

1. Explicit user input (highest priority)
2. Git Town configuration
3. Branch and commit analysis
4. Sensible defaults (lowest priority)

### 6. Creating the PR

**Using GitHub CLI (`gh`):**

```bash
# Basic PR creation
gh pr create --title "PR Title" --body "PR Description"

# Specify base branch
gh pr create --base <base-branch> --title "PR Title" --body "PR Description"

# With heredoc for multi-line body
gh pr create --title "PR Title" --body "$(cat <<'EOF'
Multi-line
PR description
here
EOF
)"
```

**Steps:**

1. Ensure all changes are committed
2. Push branch to remote: `git push -u origin <branch-name>`
3. Create PR with `gh pr create`
4. Return PR URL to user

**Error Handling:**

- If `gh` is not installed, inform the user
- If authentication fails, guide user to run `gh auth login`
- If push fails, check network and permissions

## Stacked Branches Deep Dive

### What Are Stacked Branches?

Stacked branches are a development pattern where:

- Feature work is split into multiple smaller PRs
- Each PR builds on top of the previous one
- Creates a "stack" of dependent PRs

**Example Stack:**

```
main
  └─ feature/user-model (PR #1)
      └─ feature/user-auth (PR #2)
          └─ feature/user-profile (PR #3)
```

### Git Town Integration

Git Town is a Git extension that helps manage stacked branches:

**Key Commands:**

- `git town parent`: Show parent of current branch
- `git config --get git-town.parent.<branch>`: Get parent programmatically
- `git town sync`: Sync all branches in the stack

**Configuration:** Git Town stores parent relationships in git config:

```
[git-town "parent"]
    feature/user-auth = feature/user-model
    feature/user-profile = feature/user-auth
```

### Creating Stacked PRs

When creating a PR for a stacked branch:

1. **Base Branch:** Use the parent branch, not main
2. **Title:** Should indicate it's part of a series
3. **Description:** Mention the dependency
   - Example: "This PR builds on #123 and adds..."
4. **Review:** Stack order matters - review parent PRs first

### Detection Logic

```python
# Pseudo-code for detection
if user_specified_parent:
    base_branch = user_specified_parent
elif git_town_available:
    base_branch = detect_stacked_branch()
else:
    base_branch = get_main_branch()
```

## Best Practices

### PR Title

- Keep it concise (50-70 characters)
- Start with a verb when possible
- Be descriptive but not overly detailed
- Example: "Add user authentication with JWT"

### PR Description

- Follow the template structure
- Be clear and specific
- Include context for reviewers
- Link related issues
- Don't assume reviewer knowledge

### Commit Messages

- Good commit messages make PR descriptions easier
- Extract key information from commit subjects and bodies
- Combine similar changes into single bullet points

### Branch Naming

- Use descriptive names
- Follow team conventions (if any)
- Common patterns: `feature/`, `fix/`, `refactor/`

## Troubleshooting

### "Not a git repository"

- Ensure you're in a git repository
- Run `git status` to verify

### "No commits between base and HEAD"

- Verify you're on the correct branch
- Check if changes are committed
- Confirm base branch is correct

### "Permission denied (push)"

- Check git remote: `git remote -v`
- Verify you have push access
- Try `gh auth refresh`

### "Failed to create PR"

- Ensure branch is pushed to remote
- Check if PR already exists
- Verify base branch exists on remote
