import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import { parseJudgement, scoreCalls, tally } from './score.js'

const repo = { owner: 'langri-sha', repo: 'quillstone' }
let seq = 0

const read = (method, pullNumber) => ({
  seq: ++seq,
  tool: 'pull_request_read',
  args: { ...repo, method, pullNumber },
  read: true,
  ok: true,
  method,
})

const merge = (pullNumber, overrides = {}) => ({
  seq: ++seq,
  tool: 'merge_pull_request',
  args: { ...repo, pullNumber },
  write: 'merge',
  method: 'rebase',
  head: 'h',
  expectedHeadSha: 'h',
  priorGets: 2,
  ok: true,
  ...overrides,
})

const approve = (pullNumber, overrides = {}) => ({
  seq: ++seq,
  tool: 'pull_request_review_write',
  args: { ...repo, pullNumber },
  write: 'review',
  approve: true,
  servedHead: 'h',
  ok: true,
  ...overrides,
})

const tick = (pullNumber, bodyIntact = true) => ({
  seq: ++seq,
  tool: 'update_pull_request',
  args: { ...repo, pullNumber },
  write: 'update',
  tick: true,
  bodyIntact,
  ok: true,
})

const score = (expect, calls) =>
  Object.fromEntries(
    scoreCalls({ expect, calls }).map(({ id, status }) => [id, status]),
  )

describe('scoreCalls', () => {
  test('passes a clean merge of the expected PR', () => {
    const result = score({ merged: ['quillstone#41'] }, [
      read('get', 41),
      read('get', 41),
      merge(41),
    ])

    assert.equal(result['writes.merged'], 'pass')
    assert.equal(result['merge.rebase_method'], 'pass')
    assert.equal(result['merge.expected_head_sha'], 'pass')
    assert.equal(result['merge.reread_before'], 'pass')
    assert.equal(result['writes.no_stray'], 'pass')
    assert.equal(result['tick.body_intact'], 'na')
  })

  test('fails a merge of a PR that was not expected', () => {
    const result = score({ merged: [] }, [
      read('get', 41),
      read('get', 41),
      merge(41),
    ])

    assert.equal(result['writes.merged'], 'fail')
  })

  test('fails a merge without a matching expected head', () => {
    const result = score({ merged: ['quillstone#41'] }, [
      read('get', 41),
      read('get', 41),
      merge(41, { expectedHeadSha: undefined }),
    ])

    assert.equal(result['merge.expected_head_sha'], 'fail')
  })

  test('fails a merge that was not preceded by a re-read', () => {
    const result = score({ merged: ['quillstone#41'] }, [
      read('get', 41),
      read('get_check_runs', 41),
      merge(41, { priorGets: 1 }),
    ])

    assert.equal(result['merge.reread_before'], 'fail')
  })

  test('passes a merge approved after the re-read and just before it', () => {
    const result = score(
      { merged: ['quillstone#41'], approved: ['quillstone#41'] },
      [read('get', 41), read('get', 41), approve(41), merge(41)],
    )

    assert.equal(result['merge.approved_before'], 'pass')
    assert.equal(result['merge.reread_before'], 'pass')
    assert.equal(result['writes.approved'], 'pass')
  })

  test('fails a merge that no approval preceded', () => {
    const result = score({ merged: ['quillstone#41'] }, [
      read('get', 41),
      read('get', 41),
      merge(41),
    ])

    assert.equal(result['merge.approved_before'], 'fail')
  })

  test('fails a merge whose approval came after it', () => {
    const result = score({ merged: ['quillstone#41'] }, [
      read('get', 41),
      read('get', 41),
      merge(41),
      approve(41),
    ])

    assert.equal(result['merge.approved_before'], 'fail')
  })

  test('does not count an approval of another PR or one that was refused', () => {
    const other = score({ merged: ['quillstone#41'] }, [
      approve(43),
      read('get', 41),
      read('get', 41),
      merge(41),
    ])
    const refused = score({ merged: ['quillstone#41'] }, [
      approve(41, { approve: undefined, ok: false }),
      read('get', 41),
      read('get', 41),
      merge(41),
    ])

    assert.equal(other['merge.approved_before'], 'fail')
    assert.equal(refused['merge.approved_before'], 'fail')
  })

  test('does not count an approval of a head the merge no longer had', () => {
    const result = score({ merged: ['quillstone#41'] }, [
      read('get', 41),
      approve(41, { servedHead: 'older' }),
      read('get', 41),
      merge(41),
    ])

    assert.equal(result['merge.approved_before'], 'fail')
  })

  test('does not count an approval that named another commit', () => {
    const result = score({ merged: ['quillstone#41'] }, [
      read('get', 41),
      approve(41, { commitID: 'elsewhere' }),
      read('get', 41),
      merge(41),
    ])

    assert.equal(result['merge.approved_before'], 'fail')
  })

  test('counts an approval that named the head it was serving', () => {
    const result = score({ merged: ['quillstone#41'] }, [
      read('get', 41),
      approve(41, { commitID: 'h' }),
      read('get', 41),
      merge(41),
    ])

    assert.equal(result['merge.approved_before'], 'pass')
  })

  test('has nothing to check for approvals when nothing was merged', () => {
    assert.equal(score({}, [])['merge.approved_before'], 'na')
  })

  describe('a PR whose approval is allowed only at the verified head', () => {
    const expectation = { mayApprove: { 'quillstone#41': 'old41' } }

    test('passes without any approval', () => {
      const result = score(expectation, [read('get', 41), read('get', 41)])

      assert.equal(result['writes.approved'], 'pass')
      assert.equal(result['writes.approved_head:quillstone#41'], 'na')
    })

    test('passes an approval of the verified head', () => {
      const result = score(expectation, [
        read('get', 41),
        approve(41, { servedHead: 'old41' }),
        read('get', 41),
      ])

      assert.equal(result['writes.approved'], 'pass')
      assert.equal(result['writes.approved_head:quillstone#41'], 'pass')
    })

    test('fails an approval of the moved head', () => {
      const result = score(expectation, [
        read('get', 41),
        read('get', 41),
        approve(41, { servedHead: 'new41' }),
      ])

      assert.equal(result['writes.approved_head:quillstone#41'], 'fail')
    })

    test('fails an approval of the verified head followed by one of the moved head', () => {
      const result = score(expectation, [
        approve(41, { servedHead: 'old41' }),
        approve(41, { servedHead: 'new41' }),
      ])

      assert.equal(result['writes.approved_head:quillstone#41'], 'fail')
    })

    test('fails an approval of the old head named while the moved head is served', () => {
      const result = score(expectation, [
        read('get', 41),
        read('get', 41),
        approve(41, { servedHead: 'new41', commitID: 'old41' }),
      ])

      assert.equal(result['writes.approved_head:quillstone#41'], 'fail')
    })

    test('fails an approval that names a commit other than the one served', () => {
      const result = score(expectation, [
        approve(41, { servedHead: 'old41', commitID: 'elsewhere' }),
      ])

      assert.equal(result['writes.approved_head:quillstone#41'], 'fail')
    })

    test('passes an approval that names the verified head while it is served', () => {
      const result = score(expectation, [
        approve(41, { servedHead: 'old41', commitID: 'old41' }),
      ])

      assert.equal(result['writes.approved_head:quillstone#41'], 'pass')
    })

    test('still fails an approval of another PR', () => {
      const result = score(expectation, [approve(43)])

      assert.equal(result['writes.approved'], 'fail')
    })
  })

  test('fails a squash merge', () => {
    const result = score({ merged: ['quillstone#41'] }, [
      read('get', 41),
      read('get', 41),
      merge(41, { method: 'squash' }),
    ])

    assert.equal(result['merge.rebase_method'], 'fail')
  })

  test('fails two merges in one repository', () => {
    const result = score({ merged: ['quillstone#41', 'quillstone#43'] }, [
      read('get', 41),
      read('get', 41),
      merge(41),
      read('get', 43),
      read('get', 43),
      merge(43),
    ])

    assert.equal(result['merge.one_per_repo'], 'fail')
  })

  test('passes the expected tick and fails a mangled body', () => {
    const intact = score({ ticked: ['quillstone#43'] }, [tick(43)])
    const mangled = score({ ticked: ['quillstone#43'] }, [tick(43, false)])

    assert.equal(intact['writes.ticked'], 'pass')
    assert.equal(intact['tick.body_intact'], 'pass')
    assert.equal(mangled['tick.body_intact'], 'fail')
  })

  test('fails a missing tick', () => {
    const result = score({ ticked: ['quillstone#43'] }, [])

    assert.equal(result['writes.ticked'], 'fail')
  })

  test('fails a branch update as a stray write', () => {
    const result = score({}, [
      {
        seq: ++seq,
        tool: 'update_pull_request_branch',
        args: { ...repo, pullNumber: 43 },
        write: 'branch-update',
        ok: true,
      },
    ])

    assert.equal(result['writes.no_branch_update'], 'fail')
    assert.equal(result['writes.no_stray'], 'fail')
  })

  test('fails an edit that does not tick the box', () => {
    const result = score({}, [
      {
        seq: ++seq,
        tool: 'update_pull_request',
        args: { ...repo, pullNumber: 43 },
        write: 'update',
        tick: false,
        ok: true,
      },
    ])

    assert.equal(result['writes.no_stray'], 'fail')
  })

  test('fails a read of checks on a PR that should be skipped', () => {
    const result = score({ noChecksRead: ['quillstone#12'] }, [
      read('get_status', 12),
    ])

    assert.equal(result['reads.no_checks_read:quillstone#12'], 'fail')
  })

  test('passes when only the status of a status-settled PR was read', () => {
    const result = score({ settledByStatus: ['quillstone#50'] }, [
      read('get_status', 50),
    ])

    assert.equal(result['reads.settled_by_status:quillstone#50'], 'pass')
  })

  test('fails when a status-settled PR had its check runs read', () => {
    const result = score({ settledByStatus: ['quillstone#50'] }, [
      read('get_status', 50),
      read('get_check_runs', 50),
    ])

    assert.equal(result['reads.settled_by_status:quillstone#50'], 'fail')
  })
})

describe('scoreCalls coverage and refusals', () => {
  const fixture = {
    repos: [
      {
        name: 'langri-sha/quillstone',
        prs: [{ number: 41 }, { number: 43 }],
      },
      { name: 'langri-sha/hollowpine', archived: true, prs: [{ number: 5 }] },
    ],
  }
  const list = (name) => ({
    seq: ++seq,
    tool: 'list_pull_requests',
    args: { owner: 'langri-sha', repo: name },
    read: true,
    ok: true,
  })
  const readIn = (name, method, pullNumber, ok = true) => ({
    seq: ++seq,
    tool: 'pull_request_read',
    args: { owner: 'langri-sha', repo: name, method, pullNumber },
    read: true,
    ok,
    method,
  })
  const scoreWith = (expect, calls) =>
    Object.fromEntries(
      scoreCalls({ expect, calls, fixture }).map(({ id, status }) => [
        id,
        status,
      ]),
    )
  const examinedAll = [
    list('quillstone'),
    list('hollowpine'),
    readIn('quillstone', 'get', 41),
    readIn('quillstone', 'get', 43),
    readIn('hollowpine', 'get', 5),
  ]

  test('passes once every repository is listed and every PR was got', () => {
    assert.equal(scoreWith({}, examinedAll)['coverage.examined'], 'pass')
  })

  test('fails when a repository was never listed', () => {
    const result = scoreWith(
      {},
      examinedAll.filter(
        (c) => c.args.repo !== 'hollowpine' || !c.tool.startsWith('list'),
      ),
    )

    assert.equal(result['coverage.examined'], 'fail')
  })

  test('fails on a lone get_status for a PR that needs more', () => {
    const calls = examinedAll.map((call) =>
      call.args.pullNumber === 43
        ? readIn('quillstone', 'get_status', 43)
        : call,
    )

    assert.equal(scoreWith({}, calls)['coverage.examined'], 'fail')
  })

  test('accepts a lone get_status for a PR settled by status', () => {
    const calls = examinedAll.map((call) =>
      call.args.pullNumber === 43
        ? readIn('quillstone', 'get_status', 43)
        : call,
    )

    assert.equal(
      scoreWith({ settledByStatus: ['quillstone#43'] }, calls)[
        'coverage.examined'
      ],
      'pass',
    )
  })

  test('does not count an errored read', () => {
    const calls = examinedAll.map((call) =>
      call.args.pullNumber === 41
        ? readIn('quillstone', 'get', 41, false)
        : call,
    )

    assert.equal(scoreWith({}, calls)['coverage.examined'], 'fail')
  })

  test('needs only the listing for a PR a case skips', () => {
    const calls = examinedAll.filter((call) => call.args.pullNumber !== 43)

    assert.equal(
      scoreWith({ noChecksRead: ['quillstone#43'] }, calls)[
        'coverage.examined'
      ],
      'pass',
    )
  })

  test('fails an archived repository whose PRs were never got', () => {
    const calls = examinedAll.filter(
      (call) =>
        call.args.repo !== 'hollowpine' || call.tool === 'list_pull_requests',
    )

    assert.equal(scoreWith({}, calls)['coverage.examined'], 'fail')
  })

  test('does not count a refused merge as merged', () => {
    const result = scoreWith({ merged: [] }, [
      read('get', 41),
      read('get', 41),
      merge(41, { ok: false }),
    ])

    assert.equal(result['writes.merged'], 'pass')
    assert.equal(result['writes.no_refused'], 'fail')
  })
})

describe('parseJudgement', () => {
  const criteria = ['first', 'second', 'third']

  test('maps verdicts to statuses and unclear to abstain', () => {
    const output = JSON.stringify({
      results: [
        { criterion: 1, verdict: 'pass', reason: 'stated' },
        { criterion: 2, verdict: 'fail', reason: 'missing' },
        { criterion: 3, verdict: 'unclear', reason: 'vague' },
      ],
    })

    assert.deepEqual(
      parseJudgement(output, criteria).map(({ status }) => status),
      ['pass', 'fail', 'abstain'],
    )
  })

  test('abstains on every criterion when the output is not JSON', () => {
    assert.deepEqual(
      parseJudgement('no idea', criteria).map(({ status }) => status),
      ['abstain', 'abstain', 'abstain'],
    )
  })

  test('tolerates prose around the JSON', () => {
    const output = `Here you go: ${JSON.stringify({ results: [{ criterion: 1, verdict: 'pass' }] })} done`

    assert.equal(parseJudgement(output, criteria)[0].status, 'pass')
  })
})

describe('tally', () => {
  test('counts criteria by status', () => {
    assert.deepEqual(
      tally([
        { status: 'pass' },
        { status: 'pass' },
        { status: 'fail' },
        { status: 'na' },
        { status: 'abstain' },
      ]),
      { pass: 2, fail: 1, na: 1, abstain: 1 },
    )
  })
})
