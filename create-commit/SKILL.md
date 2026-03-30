---
name: create-commit
description: Use this whenever creating Git commits.
---

# Create Commit

## Overview

This skill helps create atomic commits with proper structure and messaging. It
analyzes staged git changes to:

1. **Determine optimal commit boundaries** - Identify when changes should be
   split into multiple commits vs. kept together
2. **Generate appropriate commit messages** - Create subject lines that follow
   the project's format (Jira-prefixed for letsdeel repos)
3. **Detect fixup commits** - Recognize when changes are fixing/editing previous
   work rather than introducing new functionality
4. **Ensure code quality** - Verify that commits leave the codebase in a valid
   state and don't arbitrarily split atomic units

## Core Principles for Atomic Commits

Reference `references/atomic-commits.md` for detailed guidance. Key principles:

1. **One logical feature or fix per commit** - Each commit accomplishes a
   single, well-defined goal
2. **Tests travel with implementation** - Unit tests for a feature belong in the
   same commit as the feature
3. **Related changes stay together** - Files that work together for one goal are
   committed together
4. **Refactoring is separate** - Refactoring and feature work get different
   commits
5. **Detect fixup candidates** - When changes are editing/correcting previous
   work, suggest using `fixup!` format

## Commit Message Format

Reference `references/commit-format.md` for complete format specifications. Key
rules:

**For letsdeel repositories with Jira-prefixed branches:**

- Branch format: `GHOST-200-description` or `PROJECT-123-description`
- Commit format: `PROJECT-123 Description of changes`
- Extract the project ID from the branch name and use it as the commit subject
  prefix

**For all other cases:**

- Use clear, descriptive subject lines without a specific format requirement
- Use imperative mood ("Add", "Fix", "Implement")
- Keep subject lines concise (50 characters)

**For fixup commits:**

- Use format: `fixup! Previous commit subject`
- This indicates changes that fix/correct a previous commit rather than
  introducing new functionality

## Workflow

When analyzing git changes:

1. **Identify the repository owner** - Is this a letsdeel repo?
   - If yes, extract the Jira project ID from the current branch
   - If no, use flexible format requirements

2. **Analyze the staged changes**
   - Group changes by logical concern/feature
   - Check if tests and implementation are together
   - Look for unrelated systems being changed together

3. **Determine commit boundaries**
   - Should changes be one commit or multiple?
   - Are there changes that fix previous work (fixup candidate)?
   - Does each commit leave the code in a valid state?

4. **Generate commit message**
   - For letsdeel repos: `PROJECT-ID Description`
   - For others: Clear, concise description
   - If fixing previous work: Use `fixup!` format

5. **Validate atomicity**
   - Can you describe the commit in one clear sentence?
   - Does it accomplish a complete logical unit?
   - Are tests and implementation together (if applicable)?

## Resources

This skill includes reference documentation to guide atomic commit creation:

- **`references/atomic-commits.md`** - Comprehensive guide to atomic commit
  principles, including decision trees and red flags
- **`references/commit-format.md`** - Format specifications for commit messages
  (Jira-prefixed for letsdeel repos, flexible otherwise)
