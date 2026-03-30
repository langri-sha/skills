# Atomic Commits Guide

## What is an Atomic Commit?

An atomic commit is a self-contained unit of work that:

- Accomplishes a single, well-defined goal
- Can stand alone and make sense to someone reviewing it
- Leaves the codebase in a valid, working state
- Is neither too large (unrelated changes bundled together) nor too small
  (arbitrary splits of a single feature)

## Core Principles

### 1. One Logical Feature or Fix Per Commit

Each commit should represent one discrete piece of functionality or bug fix. If
you find yourself using "and" in the commit message, consider splitting it.

**Good (two commits):**

```
Commit 1: Add user authentication module
Commit 2: Integrate authentication into login page
```

**Bad (one commit with mixed concerns):**

```
Add user authentication module and integrate it into login page
```

### 2. Tests and Implementation Go Together

Tests that verify a feature belong in the same commit as the feature itself.
This ensures:

- The commit is reviewable as a complete unit
- Tests pass at this point in history
- The feature and its test coverage move together

**Example:**

```
Commit: Add password strength validation
Changes:
  - Implement validation logic in auth/password.py
  - Add unit tests in tests/auth/test_password.py
  - Update validation rules in config
```

### 3. Related File Changes Stay Together

Files that work together to accomplish the same goal should be committed
together. For example:

- Component file + CSS/styling file
- Database migration + model update
- API endpoint + corresponding test

**Example:**

```
Commit: Create user profile card component
Changes:
  - Add UserProfileCard.jsx (component)
  - Add UserProfileCard.css (styling)
  - Add UserProfileCard.test.jsx (tests)
```

### 4. Refactoring and Feature Work Are Separate

If you refactor while implementing a feature, those should be two commits. This
makes the feature changes clear and the refactoring easy to review separately.

**Example:**

```
Commit 1: Refactor user service to use dependency injection
Commit 2: Add two-factor authentication (uses refactored service)
```

## Decision Tree

When deciding if changes should be split or combined:

```
Do the changes accomplish a single logical goal?
├─ YES → Continue to next question
└─ NO → SPLIT into separate commits

Are they all necessary to achieve that goal?
├─ YES → Continue to next question
└─ NO → SPLIT into separate commits

Do they all relate to the same files/component?
├─ YES → Probably one commit ✓
└─ NO → Continue to next question

Is the commit size reasonable (under ~400 lines changed)?
├─ YES → One commit ✓
└─ NO → Consider splitting by logical subsystem
```

## Examples of Good Atomic Commits

### Example 1: Feature Implementation

```
Commit: Implement user email verification

Changes:
  - Add email verification token generation (auth/tokens.py)
  - Create email sending service (services/email.py)
  - Add verification endpoint (routes/verify_email.py)
  - Update user model to track verification status (models/user.py)
  - Add tests for all new functionality (tests/auth/, tests/services/)

Accomplishes: User can now verify their email address
```

### Example 2: Bug Fix

```
Commit: Fix race condition in session cleanup

Changes:
  - Add mutex to session cleanup routine (session.py)
  - Update session manager to use atomic operations (manager.py)
  - Add regression test (tests/test_session.py)

Accomplishes: Sessions are now cleaned up safely without data corruption
```

### Example 3: Refactoring + Feature

```
Commit 1: Extract database queries into repository pattern

Changes:
  - Create UserRepository class (repositories/user.py)
  - Move all user queries to repository (queries moved from models)
  - Update services to use repository (services/user_service.py)
  - Add tests (tests/repositories/)

Commit 2: Add user search by email

Changes:
  - Add search_by_email method to UserRepository
  - Create API endpoint (routes/users.py)
  - Add tests (tests/routes/)

Accomplishes: Code is refactored for testability, then new feature is added cleanly
```

## Red Flags for Non-Atomic Commits

- **Multiple "and"s in the subject**: "Add auth AND create profile AND fix bug"
- **Unrelated file types**: Changes to completely different systems (auth +
  database schema + UI)
- **Large line count with mixed changes**: If you can't describe the commit in
  one sentence
- **Tests for old features mixed with new ones**: Tests should travel with their
  implementation
- **"Work in progress" feeling**: Incomplete implementations that need follow-up
  commits to finish
