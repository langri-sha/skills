# Recovery registration

Perform this after acknowledgement and before a full transfer. In `--dry-run`
only describe the required registration; in `--rehearse` verify available
identity evidence and report gaps without changing recovery configuration.

## Verify the native identity

Have the successor report its session ID from its own harness environment or
session metadata, and independently prove its pane through tty-based seat
detection. Match that exact ID against the native transcript's metadata and cwd.
Confirm the destination is running the intended harness. Missing labels or a
process tree without a session argument are not grounds for guessing.
Disagreement between these sources blocks closure until resolved.

Write `recovery.md` in the handoff directory with the source and successor
harness/session/pane IDs, transcript paths, handoff path, actual working
directory, selected model/effort and permission constraints. Include the exact,
shell-quoted resume command for each harness, verified against its installed CLI
help. Codex resumes its own native session, never the predecessor's Claude ID.
Preserve `--no-daemon` where the app requires it and do not broaden permissions
on resume. These records link each successor to its predecessor; retain earlier
records when a session adapts again.

## Register and check the installed recovery path

Inspect the installed recovery skill or session manager's read-only inventory or
plan before writing metadata. Identify which fields it actually consumes; do not
assume generic session labels are supported. In the Herdr app, the native labels
are `codex.session` and `claude.session`. Register only the verified
destination's appropriate identity, for example:

```sh
hc label DESTINATION codex.session=VERIFIED_CODEX_SESSION
```

Clear a stale other-harness session label on that destination only after proving
it belongs to the predecessor, not another live agent. Never copy source labels
wholesale or erase the source's recovery identity while it still owns the work.
Store cwd, model and permission data in the supported recovery fields; keep any
unsupported details explicit in `recovery.md`.

Read the destination metadata back and run the recovery mechanism's read-only
selection/plan, if supported. Check that a stopped successor would select the
right harness, native session, cwd and permission mode, and would not resurrect
the predecessor as the active owner. When the plan omits running agents, inspect
its stopped-agent selection logic without stopping either pane. Record what was
verified and what remains untested. Do not reboot, kill or restart live sessions
to test recovery as part of adaptation.

If the installed restore path skips Codex, still chooses Claude, cannot preserve
permissions, or offers no way to establish the selection, report that as a
transfer blocker and retain the source. A stored label and a manual resume
command are useful recovery evidence, but do not prove automatic recovery. Do
not silently modify the restore implementation under this skill. A user may
explicitly accept manual recovery; record that exception and the exact resume
command before continuing.

When ownership transfers, make the source's retired status and successor link
explicit in `transfer.md` and any supported recovery registry. On resume, read
this record before acting: the predecessor must not restart project work when
its successor already owns it. Never delete the source transcript to prevent a
duplicate resume.
