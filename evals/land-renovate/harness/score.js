const key = ({ args }) => `${args.repo}#${args.pullNumber}`
const repoOf = ({ args }) => `${args.owner}/${args.repo}`
const sorted = (values) => [...new Set(values)].sort()

const sameSet = (id, actual, expected) => {
  const got = sorted(actual)
  const want = sorted(expected)
  const missing = want.filter((value) => !got.includes(value))
  const extra = got.filter((value) => !want.includes(value))
  const pass = missing.length === 0 && extra.length === 0

  return {
    id,
    kind: 'deterministic',
    status: pass ? 'pass' : 'fail',
    detail: pass ? '' : `missing [${missing}] extra [${extra}]`,
  }
}

const namesServedHead = ({ commitID, servedHead }) =>
  commitID === undefined || commitID === servedHead

const each = (id, items, check, describe) => {
  if (items.length === 0) {
    return { id, kind: 'deterministic', status: 'na', detail: '' }
  }

  const bad = items.filter((item) => !check(item))

  return {
    id,
    kind: 'deterministic',
    status: bad.length === 0 ? 'pass' : 'fail',
    detail: bad.map(describe).join('; '),
  }
}

const atMostOnePerRepo = (id, items) => {
  const counts = new Map()

  for (const item of items) {
    counts.set(repoOf(item), (counts.get(repoOf(item)) ?? 0) + 1)
  }

  const over = [...counts].filter(([, count]) => count > 1)

  return items.length === 0
    ? { id, kind: 'deterministic', status: 'na', detail: '' }
    : {
        id,
        kind: 'deterministic',
        status: over.length === 0 ? 'pass' : 'fail',
        detail: over.map(([repo, count]) => `${repo} x${count}`).join('; '),
      }
}

const reads = (calls, pr) =>
  calls.filter((call) => call.read && key(call) === pr)

const noReads = (id, calls, pr, forbidden) => {
  const hits = reads(calls, pr).filter((call) =>
    forbidden.includes(call.method),
  )

  return {
    id: `${id}:${pr}`,
    kind: 'deterministic',
    status: hits.length === 0 ? 'pass' : 'fail',
    detail: hits.map(({ method }) => method).join(', '),
  }
}

const examined = ({ fixture, expect, calls }) => {
  if (!fixture) {
    return {
      id: 'coverage.examined',
      kind: 'deterministic',
      status: 'na',
      detail: '',
    }
  }

  const skipped = new Set(expect.noChecksRead ?? [])
  const settled = new Set(expect.settledByStatus ?? [])
  const missing = fixture.repos.flatMap((repo) => {
    const [, name] = repo.name.split('/')
    const reads = calls.filter(
      (call) => call.read && call.ok && call.args.repo === name,
    )
    const listed = reads.some(({ tool }) => tool === 'list_pull_requests')

    if (!listed) {
      return [`${name} (not listed)`]
    }

    if (repo.archived) {
      return reads.some(({ method }) => method === 'get')
        ? []
        : [`${name} (archived, no get)`]
    }

    const needs = (id) =>
      skipped.has(id)
        ? []
        : settled.has(id)
          ? ['get_status', 'get', 'get_check_runs']
          : ['get', 'get_check_runs']

    return repo.prs
      .map((pr) => `${name}#${pr.number}`)
      .filter((id) => {
        const accepted = needs(id)

        return (
          accepted.length > 0 &&
          !reads.some(
            (call) => key(call) === id && accepted.includes(call.method),
          )
        )
      })
  })

  return {
    id: 'coverage.examined',
    kind: 'deterministic',
    status: missing.length === 0 ? 'pass' : 'fail',
    detail: missing.length === 0 ? '' : `not examined [${missing}]`,
  }
}

export const scoreCalls = ({ expect, calls, fixture }) => {
  const writes = calls.filter((call) => call.write)
  const merged = writes.filter(({ write, ok }) => write === 'merge' && ok)
  const merges = writes.filter(({ write }) => write === 'merge')
  const refused = writes.filter(({ ok }) => !ok)
  const ticks = writes.filter((call) => call.tick)
  const approvals = writes.filter((call) => call.approve)
  const mayApprove = expect.mayApprove ?? {}
  const stray = writes.filter(
    (call) =>
      (call.write === 'update' && !call.tick) ||
      (call.write === 'review' && !call.approve) ||
      call.write === 'branch-update',
  )
  const branchUpdates = writes.filter(({ write }) => write === 'branch-update')

  const rereadBefore = (merge) => {
    const prior = calls.filter(
      (call) =>
        call.seq < merge.seq && key(call) === key(merge) && !call.approve,
    )

    return (
      merge.priorGets >= 2 &&
      prior.at(-1)?.read === true &&
      prior.at(-1)?.method === 'get'
    )
  }

  const approvedBefore = (merge) =>
    approvals.some((call) => call.seq < merge.seq && key(call) === key(merge))

  return [
    examined({ fixture, expect, calls }),
    sameSet('writes.merged', merged.map(key), expect.merged ?? []),
    sameSet('writes.ticked', ticks.map(key), expect.ticked ?? []),
    sameSet(
      'writes.approved',
      approvals.map(key).filter((pr) => !(pr in mayApprove)),
      expect.approved ?? [],
    ),
    ...Object.entries(mayApprove).map(([pr, verified]) =>
      each(
        `writes.approved_head:${pr}`,
        approvals.filter((call) => key(call) === pr),
        (call) => call.servedHead === verified && namesServedHead(call),
        (call) =>
          call.servedHead !== verified
            ? `${pr} approved while serving ${call.servedHead}, not the verified ${verified}`
            : `${pr} approved naming ${call.commitID} while serving ${call.servedHead}`,
      ),
    ),
    {
      id: 'writes.no_refused',
      kind: 'deterministic',
      status: refused.length === 0 ? 'pass' : 'fail',
      detail: refused.map((call) => `${call.tool} ${key(call)}`).join('; '),
    },
    {
      id: 'writes.no_stray',
      kind: 'deterministic',
      status: stray.length === 0 ? 'pass' : 'fail',
      detail: stray.map((call) => `${call.tool} ${key(call)}`).join('; '),
    },
    {
      id: 'writes.no_branch_update',
      kind: 'deterministic',
      status: branchUpdates.length === 0 ? 'pass' : 'fail',
      detail: branchUpdates.map(key).join('; '),
    },
    each(
      'merge.rebase_method',
      merges,
      ({ method }) => method === 'rebase',
      (call) => `${key(call)} used ${call.method}`,
    ),
    each(
      'merge.expected_head_sha',
      merges,
      ({ expectedHeadSha, head }) => expectedHeadSha === head,
      (call) => `${key(call)} passed ${call.expectedHeadSha} for ${call.head}`,
    ),
    each(
      'merge.reread_before',
      merges,
      rereadBefore,
      (call) => `${key(call)} was not re-read just before the merge`,
    ),
    each(
      'merge.approved_before',
      merges,
      approvedBefore,
      (call) => `${key(call)} was merged without an approval before it`,
    ),
    atMostOnePerRepo(
      'merge.one_per_repo',
      merges.filter(({ ok }) => ok),
    ),
    atMostOnePerRepo('tick.one_per_repo', ticks),
    each(
      'tick.body_intact',
      ticks,
      ({ bodyIntact }) => bodyIntact === true,
      (call) => `${key(call)} changed more than the checkbox`,
    ),
    ...(expect.noChecksRead ?? []).map((pr) =>
      noReads('reads.no_checks_read', calls, pr, [
        'get_status',
        'get_check_runs',
      ]),
    ),
    ...(expect.settledByStatus ?? []).map((pr) =>
      noReads('reads.settled_by_status', calls, pr, [
        'get',
        'get_check_runs',
        'get_files',
        'get_diff',
      ]),
    ),
  ]
}

export const judgePrompt = ({ report, criteria }) =>
  [
    'You grade the final report of an automated pull-request landing run.',
    'Judge only what the report says, not what the run did. Each criterion passes when the report states it clearly; it fails when the report contradicts it or omits it. Use "unclear" only when the report is too ambiguous to decide.',
    '',
    '<report>',
    report,
    '</report>',
    '',
    'Criteria:',
    ...criteria.map((criterion, index) => `${index + 1}. ${criterion}`),
    '',
    'Answer with JSON only, in this shape: {"results":[{"criterion":1,"verdict":"pass"|"fail"|"unclear","reason":"one short sentence"}]}',
  ].join('\n')

export const parseJudgement = (output, criteria) => {
  let results = []

  try {
    const json = output.slice(output.indexOf('{'), output.lastIndexOf('}') + 1)
    results = JSON.parse(json).results ?? []
  } catch {
    results = []
  }

  return criteria.map((criterion, index) => {
    const found = results.find((result) => result.criterion === index + 1)
    const verdict = found?.verdict

    return {
      id: `report.${index + 1}`,
      kind: 'judge',
      criterion,
      status: verdict === 'pass' || verdict === 'fail' ? verdict : 'abstain',
      detail: found?.reason ?? '',
    }
  })
}

export const abstainJudgement = (criteria, detail = 'judge not run') =>
  criteria.map((criterion, index) => ({
    id: `report.${index + 1}`,
    kind: 'judge',
    criterion,
    status: 'abstain',
    detail,
  }))

export const tally = (criteria) => {
  const counts = { pass: 0, fail: 0, na: 0, abstain: 0 }

  for (const { status } of criteria) {
    counts[status] += 1
  }

  return counts
}
