import { REBASE_CHECKED, REBASE_UNCHECKED, renovateBody } from './body.js'

const BOT = 'renovate[bot]'
const MERGE_READY = new Set(['clean', 'has_hooks'])

const defaultFiles = ({ update, title }) =>
  update
    ? [
        {
          filename: 'package.json',
          patch: `@@ -1,3 +1,3 @@\n-"${update.package}": "${update.from}"\n+"${update.package}": "${update.to}"`,
        },
        { filename: 'pnpm-lock.yaml', patch: '@@ -10,3 +10,3 @@\n-old\n+new' },
      ]
    : [
        {
          filename: 'pnpm-lock.yaml',
          patch: `@@ -1,3 +1,3 @@\n-old\n+new\n# ${title}`,
        },
      ]

const normalizeCommits = (def) =>
  def.commits ?? [
    { sha: def.head, author: BOT, message: def.title ?? 'Renovate update' },
  ]

const normalizeChecks = (checks = []) =>
  checks.map((check) =>
    Array.isArray(check)
      ? { name: check[0], status: check[1], conclusion: check[2] ?? null }
      : check,
  )

const normalizeStatuses = (statuses = []) =>
  statuses.map((status) =>
    Array.isArray(status)
      ? { context: status[0], state: status[1], description: status[2] ?? '' }
      : status,
  )

const phaseOf = (def, overrides = {}) => {
  const merged = { ...def, ...overrides }
  const commits = normalizeCommits(merged)

  return {
    head: commits.at(-1).sha,
    commits,
    base: merged.base,
    mergeable: merged.mergeable ?? true,
    state: merged.state ?? 'clean',
    statuses: normalizeStatuses(merged.statuses),
    checks: normalizeChecks(merged.checks),
    whenApproved: merged.whenApproved ?? false,
  }
}

const combinedState = (statuses) => {
  if (statuses.some((status) => ['failure', 'error'].includes(status.state))) {
    return 'failure'
  }

  if (statuses.length === 0 || statuses.some((s) => s.state === 'pending')) {
    return 'pending'
  }

  return 'success'
}

const text = (value) => ({
  content: [
    {
      type: 'text',
      text: typeof value === 'string' ? value : JSON.stringify(value),
    },
  ],
})

const failure = (message) => ({ ...text(message), isError: true })

const paginate = (items, { perPage = 30, page = 1 } = {}) =>
  items.slice((page - 1) * perPage, page * perPage)

const QUIET_REPOSITORIES = ['langri-sha/skills', 'example-org/harbourlight']

export const createWorld = (fixture) => {
  const repos = new Map()
  const calls = []

  for (const name of QUIET_REPOSITORIES) {
    repos.set(name, { name, tip: 'quiet0001', branch: 'main', prs: new Map() })
  }

  for (const repoDef of fixture.repos) {
    const repo = {
      ...repoDef,
      branch: repoDef.branch ?? 'main',
      tip: repoDef.tip,
      prs: new Map(),
    }

    for (const def of repoDef.prs) {
      const override = def.reread
      const phases = [phaseOf(def)]

      if (override) {
        phases.push(phaseOf(def, override))
      }

      const body =
        def.body ??
        renovateBody({
          title: def.title,
          update: def.update,
          bytes: def.bodyBytes,
        })

      repo.prs.set(def.number, {
        def,
        phases,
        gets: 0,
        body,
        originalBody: body,
        approved: false,
        merged: false,
      })
    }

    repos.set(repoDef.name, repo)
  }

  const phase = (pr) => {
    let index = Math.min(Math.max(pr.gets - 1, 0), pr.phases.length - 1)

    while (index > 0 && pr.phases[index].whenApproved && !pr.approved) {
      index -= 1
    }

    return pr.phases[index]
  }

  const locate = ({ owner, repo, pullNumber }) => {
    const repository = repos.get(`${owner}/${repo}`)

    if (!repository) {
      return { error: failure('Not Found: repository not found') }
    }

    if (pullNumber === undefined) {
      return { repository }
    }

    const pr = repository.prs.get(Number(pullNumber))

    return pr
      ? { repository, pr }
      : { error: failure(`Not Found: pull request ${pullNumber} not found`) }
  }

  const summary = (repository, pr) => {
    const current = phase(pr)

    return {
      number: pr.def.number,
      title: pr.def.title,
      state: pr.merged ? 'closed' : 'open',
      draft: false,
      user: { login: pr.def.author ?? BOT },
      html_url: `https://github.com/${repository.name}/pull/${pr.def.number}`,
      head: {
        ref: `renovate/${pr.def.number}`,
        sha: current.head,
        repo: { full_name: repository.name },
      },
      base: {
        ref: repository.branch,
        sha: current.base,
        repo: { full_name: repository.name },
      },
    }
  }

  const detail = (repository, pr) => {
    const current = phase(pr)
    const files = pr.def.files ?? defaultFiles(pr.def)

    return {
      ...summary(repository, pr),
      body: pr.body,
      merged: pr.merged,
      mergeable: current.mergeable,
      mergeable_state: current.state,
      commits: current.commits.length,
      changed_files: files.length,
      base: {
        ref: repository.branch,
        sha: current.base,
        repo: {
          full_name: repository.name,
          archived: Boolean(repository.archived),
        },
      },
    }
  }

  const record = (tool, args, meta = {}) => {
    calls.push({ seq: calls.length + 1, tool, args, ...meta })
  }

  const read = (args) => {
    const { method } = args
    const located = locate(args)

    if (located.error) {
      return located.error
    }

    const { repository, pr } = located

    if (method === 'get') {
      pr.gets += 1
      return text(detail(repository, pr))
    }

    const current = phase(pr)

    if (method === 'get_status') {
      return text({
        sha: current.head,
        state: combinedState(current.statuses),
        total_count: current.statuses.length,
        statuses: current.statuses,
      })
    }

    if (method === 'get_check_runs') {
      return text({
        total_count: current.checks.length,
        check_runs: current.checks.map((check, index) => ({
          id: index + 1,
          head_sha: current.head,
          ...check,
        })),
      })
    }

    if (method === 'get_files') {
      return text(pr.def.files ?? defaultFiles(pr.def))
    }

    if (method === 'get_diff') {
      return text(
        (pr.def.files ?? defaultFiles(pr.def))
          .map(
            ({ filename, patch }) =>
              `diff --git a/${filename} b/${filename}\n${patch}`,
          )
          .join('\n'),
      )
    }

    if (method === 'get_reviews') {
      return text(
        pr.approved
          ? [{ user: { login: 'langri-sha' }, state: 'APPROVED' }]
          : [],
      )
    }

    if (method === 'get_comments' || method === 'get_review_comments') {
      return text([])
    }

    return failure(`unknown method ${method}`)
  }

  const archivedWrite = (repository) =>
    repository.archived
      ? failure(
          'HTTP 403: Repository was archived so is read-only. (https://api.github.com)',
        )
      : null

  const tools = {
    list_pull_requests(args) {
      const located = locate(args)

      if (located.error) {
        return located.error
      }

      const { repository } = located
      const direction = args.direction ?? 'desc'
      const state = args.state ?? 'open'
      const open = [...repository.prs.values()]
        .filter(
          (pr) =>
            state === 'all' || (state === 'closed' ? pr.merged : !pr.merged),
        )
        .sort((a, b) =>
          direction === 'asc'
            ? a.def.number - b.def.number
            : b.def.number - a.def.number,
        )

      return text(
        paginate(
          open.map((pr) => summary(repository, pr)),
          args,
        ),
      )
    },

    pull_request_read: read,

    list_commits(args) {
      const located = locate(args)

      if (located.error) {
        return located.error
      }

      const { repository } = located
      const ref = args.sha ?? repository.branch

      if (ref !== repository.branch) {
        return failure(`No commit found for SHA: ${ref}`)
      }

      return text(
        paginate(
          [
            {
              sha: repository.tip,
              commit: { message: 'Merge', author: { name: 'maintainer' } },
              author: { login: 'maintainer' },
            },
          ],
          args,
        ),
      )
    },

    pull_request_review_write(args) {
      const located = locate(args)

      if (located.error) {
        return located.error
      }

      const { repository, pr } = located
      const refused = archivedWrite(repository)

      if (refused) {
        record('pull_request_review_write', args, {
          write: 'review',
          ok: false,
        })
        return refused
      }

      const approve = String(args.event).toUpperCase() === 'APPROVE'

      if (approve) {
        pr.approved = true
      }

      record('pull_request_review_write', args, {
        write: 'review',
        approve,
        ok: true,
      })

      return text({ id: 1, state: approve ? 'APPROVED' : 'COMMENTED' })
    },

    merge_pull_request(args) {
      const located = locate(args)

      if (located.error) {
        return located.error
      }

      const { repository, pr } = located
      const current = phase(pr)
      const meta = {
        write: 'merge',
        head: current.head,
        method: args.merge_method,
        expectedHeadSha: args.expectedHeadSha,
        priorGets: pr.gets,
      }
      const refuse = (message) => {
        record('merge_pull_request', args, { ...meta, ok: false })
        return failure(message)
      }
      const refused = archivedWrite(repository)

      if (refused) {
        record('merge_pull_request', args, { ...meta, ok: false })
        return refused
      }

      if (pr.merged) {
        return refuse('HTTP 405: Pull Request is not mergeable')
      }

      if (args.expectedHeadSha && args.expectedHeadSha !== current.head) {
        return refuse(
          'HTTP 409: Head branch was modified. Review and try the merge again.',
        )
      }

      const blocked =
        current.state === 'dirty' ||
        (current.state === 'blocked' &&
          repository.requiresReview &&
          !pr.approved)

      if (blocked) {
        return refuse(
          current.state === 'dirty'
            ? 'HTTP 405: Pull Request is not mergeable'
            : 'HTTP 405: At least 1 approving review is required by reviewers with write access.',
        )
      }

      pr.merged = true
      repository.tip = `merge-${pr.def.number}`
      record('merge_pull_request', args, {
        ...meta,
        ok: true,
        ready: MERGE_READY.has(current.state) || pr.approved,
      })

      return text({
        merged: true,
        sha: repository.tip,
        message: 'Pull Request successfully merged',
      })
    },

    update_pull_request(args) {
      const located = locate(args)

      if (located.error) {
        return located.error
      }

      const { repository, pr } = located
      const refused = archivedWrite(repository)

      if (refused) {
        record('update_pull_request', args, { write: 'update', ok: false })
        return refused
      }

      const tick =
        typeof args.body === 'string' &&
        pr.body.includes(REBASE_UNCHECKED) &&
        args.body.includes(REBASE_CHECKED)
      const bodyIntact =
        tick &&
        args.body === pr.originalBody.replace(REBASE_UNCHECKED, REBASE_CHECKED)

      if (typeof args.body === 'string') {
        pr.body = args.body
      }

      record('update_pull_request', args, {
        write: 'update',
        tick,
        bodyIntact,
        ok: true,
      })

      return text(summary(repository, pr))
    },

    update_pull_request_branch(args) {
      const located = locate(args)

      if (located.error) {
        return located.error
      }

      const { repository, pr } = located
      const meta = { write: 'branch-update' }
      const refused = archivedWrite(repository)

      if (refused) {
        record('update_pull_request_branch', args, { ...meta, ok: false })
        return refused
      }

      if (args.expectedHeadSha && args.expectedHeadSha !== phase(pr).head) {
        record('update_pull_request_branch', args, { ...meta, ok: false })
        return failure(
          'HTTP 422: expected head sha didn’t match current head ref.',
        )
      }

      record('update_pull_request_branch', args, { ...meta, ok: true })

      return text({ message: 'Updating pull request branch.' })
    },
  }

  const handle = (name, args = {}) => {
    const tool = tools[name]

    if (!tool) {
      record(name, args, { unknown: true })
      return failure(`unknown tool ${name}`)
    }

    const before = calls.length
    const result = tool(args)

    if (calls.length === before) {
      record(name, args, {
        read: true,
        method: args.method,
        ok: !result.isError,
      })
    }

    return result
  }

  return { handle, calls, repos }
}
