---
name: manage-ignore-patterns
description:
  Use this skill when managing ignore patterns in .gitignore, .prettierignore,
  eslint.config.mjs, or similar files to ensure they are properly sorted and
  consistent across the project.
---

# Manage Ignore Patterns

## Overview

This skill enables consistent management of ignore patterns across multiple
configuration files in a project. It handles adding patterns to `.gitignore`,
`.prettierignore`, `eslint.config.mjs`, and similar files while maintaining
proper sorting and organization conventions.

## When to Use This Skill

Invoke this skill when:

- Adding new patterns to ignore files (e.g., `__pycache__/`, `node_modules/`)
- Maintaining consistency across multiple ignore configuration files
- Reorganizing ignore patterns for better readability
- Ensuring alphabetical sorting in ignore files

## Workflow: Adding and Organizing Ignore Patterns

### Step 1: Identify Target Files

Determine which ignore files need updating:

- **Text-based ignore files**: `.gitignore`, `.prettierignore`
- **JavaScript config files**: `eslint.config.mjs` (and similar configs with
  `ignores` arrays)

Only update files that already exist in the repository. Do not create new ignore
files.

### Step 2: Read Current Patterns

Read the target file(s) to understand the current pattern structure and
organization. Note:

- Current patterns and their organization
- Whether patterns are grouped (file patterns separate from directory patterns)
- Current sorting approach

### Step 3: Add New Patterns

When adding patterns, follow these rules:

**Sorting Strategy:**

1. **Hidden files first** - Start with `.*`
2. **File patterns** - All files (without `/`) sorted alphabetically
3. **Blank line** - Single line separating files from directories
4. **Directory patterns** - All directories (with `/`) sorted alphabetically

Example organization in a text-based ignore file:

```
.*
!.gitignore
*.log
*.tsbuildinfo
next-env.d.ts

!.cache/
!.github/
!.husky/
__pycache__/
.cache/
build/
node_modules/
playwright-report/
```

**For JavaScript config files** (like `eslint.config.mjs`):

When updating `ignores` arrays, use glob patterns following the same sorting
strategy - special patterns first, then files, then directories:

```javascript
ignores: [
  '**/.*',
  '**/.next/',
  '**/__pycache__/',
  '**/build/',
  '**/dist/',
  '**/node_modules/',
]
```

### Step 4: Update Files

Update each target file:

1. Read the file completely to understand current structure
2. Determine the proper position for new patterns based on sorting rules
3. Add patterns in the correct location
4. Ensure no duplicate patterns
5. Verify the file maintains its original structure and formatting

### Step 5: Verify and Commit

After updating:

1. Verify files are syntactically correct (text files can be checked visually;
   JS files should be validated with linters)
2. Commit changes with a descriptive message:
   `chore: add <pattern> to ignore patterns`
3. Push to the remote repository

## Common Patterns to Ignore

**Python-related:**

- `__pycache__/` - Python bytecode cache

**Node.js/npm-related:**

- `node_modules/` - Dependencies
- `pnpm-lock.yaml` - Lock file

**Build artifacts:**

- `build/` - Build output
- `dist/` - Distribution output
- `.next/` - Next.js build output
- `out/` - Alternative build output

**IDE/editor files:**

- `.*` - Hidden files (covered in most ignore files)

**Testing:**

- `playwright-report/` - Test reports

## Key Considerations

1. **Respect existing organization** - Maintain the grouping and sorting style
   already in place
2. **Update all related files** - When adding a pattern, update all relevant
   ignore files consistently
3. **No file creation** - Only update files that already exist; do not create
   new ignore files
4. **Sorting matters** - Always sort alphabetically within each group (files,
   then directories)
5. **Consistency across tools** - Ensure patterns are consistent across
   `.gitignore`, `.prettierignore`, and `eslint.config.mjs`
