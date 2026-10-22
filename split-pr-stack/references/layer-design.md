# Layer design

How to decompose a large change into a dependency-ordered stack of independently
reviewable layers, and the artifacts the plan must produce.

## Ordering rules

- Dependencies below dependents: compatible schema/types/configuration first,
  then domain behavior, then adapters/API/UI.
- Each layer must leave the repository fully valid on its own — building,
  linting, testing, migrations applying — with no reference to anything above
  it.
- Independent concerns do not belong in one stack. Stacks are strictly linear;
  independent work becomes separate PRs or separate stacks.
- If the graph cannot be linearized without artificial coupling, stop and
  propose independent PRs instead.

## Grouping rules

- Tests travel with the implementation they cover. A separate final
  integration-test layer is acceptable only for genuinely end-to-end coverage;
  every earlier layer still carries its own tests.
- Dependency declarations and their lockfile changes stay together.
- Source and the generated artifacts it requires stay together.
- Mechanical refactors separate from behavior changes — but only when both
  resulting trees remain valid.
- Migrations must be backward-compatible at every intermediate state.

## Sizing

- 2–4 layers is the target; 8 is the hard cap. (GitHub's product cap is far
  larger — currently 100 PRs per stack — but a reviewable story is not.)
- Every layer needs a one-sentence intent, a clear reviewer audience, and a
  meaningful validation path. A layer that fails any of these is not a layer;
  merge it into a neighbor.

## The layer manifest

Produce this before any mutation, and get it approved at Gate A:

```yaml
source:
  branch: feature/original
  pr: 1234 # null when splitting a worktree with no PR
  source_head: <sha>
  source_base: <sha>
  trunk: main
  trunk_sha: <sha>
policy: parallel-replacement
capability: native | fallback | local-only
layers:
  - branch: 1234-user-auth-01-schema
    intent: Add the user_credentials table and shared types
    files_or_hunks:
      - supabase/migrations/20260810_user_credentials.sql
      - lib/auth/types.ts
    validation: ['pnpm dagger:check']
    reviewer_focus: Data model and compatibility
  - branch: 1234-user-auth-02-service
    intent: Implement the auth service against the new schema
    files_or_hunks:
      - lib/auth/service.ts
      - lib/auth/service.test.ts
    validation: ['pnpm dagger:check']
    reviewer_focus: Domain behavior
remote_actions: none-until-approved
```

## Validation table

Emit after phase 4, before Gate C:

| Layer | Parent  | Intent          | Diff                     | Required checks     | Result |
| ----- | ------- | --------------- | ------------------------ | ------------------- | ------ |
| 1     | `main`  | Schema + types  | 4 files, +120/−0         | `pnpm dagger:check` | pass   |
| 2     | layer 1 | Auth service    | 6 files, +310/−12        | `pnpm dagger:check` | pass   |
| Top   | —       | End-state proof | empty vs `REFERENCE_SHA` | full suite          | pass   |

## Draft PR body template

GitHub renders the native stack map itself — do not duplicate a stale copy of
it. Each draft body stays under 150 words and follows `/create-pr`: why the
layer exists, where to start reviewing when that isn't obvious, and one line
naming what ran. In fallback mode (no native stack map), also state the
layer's position and review order in one line.

```markdown
Adds the session schema and types that the auth service in the next layer
builds on. Start at `src/schema/session.ts`.

Split from #1234, which stays open until this stack is accepted.

Validated with `pnpm dagger:check`.
```

Titles follow `/create-pr` conventions: plain, descriptive sentences, no
prefixes. Keep upper layers draft until the lower contracts stabilize, unless
reviewers explicitly want parallel review.
