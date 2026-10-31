---
"skills": patch
---

The worktree reaper checks that an hc core is listening before calling `hc`, so
a dry run no longer starts a core when none is running or a stale socket file is
left behind, and it reports any other `hc` failure or an unreadable reply as
`hc UNAVAILABLE` instead of zero terminals.
