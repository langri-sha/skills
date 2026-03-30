# Commit Message Format

## Overview

Commit message format depends on the repository ownership and whether the branch
contains a Jira project ID.

## Format Rules

### For `letsdeel` Organization Repositories

If the current branch contains a Jira project ID (format:
`PROJECT-###-description`), the commit subject **must** start with the Jira
project ID:

```
PROJECT-### Description of changes
```

**Examples:**

```
GHOST-200 Add two-factor authentication
GHOST-201 Fix login validation error
DEV-45 Implement user search feature
BACKEND-123 Optimize database query performance
```

**Guidelines:**

- Project ID comes first, separated by space from description
- Description uses imperative mood ("Add", "Fix", "Implement", not "Added",
  "Fixed")
- Maximum 50 characters including the project ID
- No period at the end

If the branch does **not** contain a Jira project ID, use a clear descriptive
subject line:

```
Brief description of changes
```

**Examples:**

```
Add email notification system
Fix memory leak in cache service
Refactor authentication module
Update documentation for API endpoints
```

### For Other Organization Repositories

No specific format requirement. Use clear, descriptive subject lines that follow
standard commit conventions.

**Examples:**

```
Add user authentication
Fix database connection pool
Implement caching strategy
Update test coverage
```

## Message Body (Optional)

Separate the subject from body with a blank line. The body should explain:

- **What** was changed
- **Why** it was changed
- Any relevant context or trade-offs

Keep body lines wrapped at 72 characters.

**Example:**

```
GHOST-200 Add two-factor authentication

- Implement TOTP-based verification
- Add recovery codes for account access
- Update user settings to manage 2FA

This improves account security by requiring a second factor
during login. Users can manage their authentication methods
in account settings.

Fixes #1234
```

## Detecting Jira Project ID from Branch

The skill will automatically extract the Jira project ID from the current branch
if it follows this pattern:

```
<PROJECT-ID>-<rest-of-branch-name>
```

Pattern matching:

- `GHOST-200-add-auth` → Extract `GHOST-200`
- `DEV-45-fix-bug` → Extract `DEV-45`
- `feature/add-cache` → No project ID (missing number pattern)
- `main` → No project ID

The project ID must:

1. Start with letters (A-Z)
2. Followed by a hyphen and one or more digits
3. Followed by another hyphen and additional characters

## Fixup Commits

When a commit should fix or amend a previous commit, indicate this clearly:

```
fixup! <previous commit subject>
```

This tells reviewers and tools (like `git rebase --autosquash`) that this commit
belongs with the previous one.

**Example:**

```
Previous commit: GHOST-200 Add password validation
Current commit: fixup! Add password validation

(Fixes a bug or completes implementation from previous commit)
```

When preparing for merge, fixup commits can be automatically squashed with their
target commit using:

```bash
git rebase -i --autosquash origin/main
```
