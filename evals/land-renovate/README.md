# land-renovate evals

Replays the hourly "Land Renovate PRs" prompt against synthetic repositories and
scores what it does. Nothing here touches GitHub.

- `prompts/v4.txt` is the candidate prompt, copied from the cloud task with a
  stand-in repository name.
- `evals.json` has the cases: `prompt` describes the snapshot, `expected_output`
  is the rubric and `files` names the fixture. The candidate sees neither the
  rubric nor `expect`.
- `fixtures/` holds each case's repositories and PRs, and the `expect` block it
  is scored on.
- `harness/mock-github.js` is a stdio MCP server named `github`. It serves the
  tools the prompt loads from a fixture and records each call.
- `harness/score.js` checks the recorded calls deterministically. A judge model
  grades only the wording of the final report.

```sh
node evals/land-renovate/harness/run.js --cases 1,2 --skill-ref origin/main
```

A run drives `claude -p` with Read, Glob, Grep, ToolSearch and the mock, in a
temporary checkout of the skill at `--skill-ref`. It refuses to score a case
unless the session's init event shows nothing else was loaded. Output goes to
`$TMPDIR/land-renovate-evals/<run>/` with a `receipt.json` pinning the skill
commit and tree, the prompt hash, the model and the settings.

It spends tokens on the candidate model, and on the judge unless `--no-judge`.
`node --test evals/land-renovate/harness/*.test.js` spends none.
