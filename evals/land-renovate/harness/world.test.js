import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import { REBASE_CHECKED, REBASE_UNCHECKED } from './body.js'
import { createWorld } from './world.js'

const repoName = { owner: 'langri-sha', repo: 'quillstone' }

const fixture = (overrides = {}) => ({
  repos: [
    {
      name: 'langri-sha/quillstone',
      tip: 'tip000001',
      prs: [
        {
          number: 41,
          title: 'Update dependency zod to v4.3.7',
          update: { package: 'zod', from: '4.3.6', to: '4.3.7', type: 'patch' },
          head: 'head00041',
          base: 'tip000001',
          statuses: [['renovate/stability-days', 'success']],
          checks: [['check / Dagger', 'completed', 'success']],
          reread: { state: 'unstable' },
        },
        {
          number: 43,
          title: 'Update dependency vite to v7.4.2',
          head: 'head00043',
          base: 'tip000001',
        },
      ],
      ...overrides,
    },
  ],
})

const call = (world, tool, args) =>
  JSON.parse(world.handle(tool, { ...repoName, ...args }).content[0].text)

describe('list_pull_requests', () => {
  test('returns open PRs newest first by default', () => {
    const world = createWorld(fixture())

    const result = call(world, 'list_pull_requests', { state: 'open' })

    assert.deepEqual(
      result.map(({ number }) => number),
      [43, 41],
    )
  })

  test('honours an ascending direction and paging', () => {
    const world = createWorld(fixture())

    const result = call(world, 'list_pull_requests', {
      direction: 'asc',
      perPage: 1,
      page: 2,
    })

    assert.deepEqual(
      result.map(({ number }) => number),
      [43],
    )
  })

  test('fails for a repository that is not in the fixture', () => {
    const world = createWorld(fixture())

    const result = world.handle('list_pull_requests', {
      owner: 'langri-sha',
      repo: 'missing',
    })

    assert.equal(result.isError, true)
  })
})

describe('pull_request_read', () => {
  test('get reports commit count, base sha and archived flag', () => {
    const world = createWorld(fixture({ archived: true }))

    const pr = call(world, 'pull_request_read', {
      method: 'get',
      pullNumber: 41,
    })

    assert.equal(pr.commits, 1)
    assert.equal(pr.base.sha, 'tip000001')
    assert.equal(pr.base.repo.archived, true)
    assert.equal(pr.mergeable_state, 'clean')
  })

  test('get_status reads pending when the head has no statuses', () => {
    const world = createWorld(fixture())

    const status = call(world, 'pull_request_read', {
      method: 'get_status',
      pullNumber: 43,
    })

    assert.deepEqual(status, {
      sha: 'head00043',
      state: 'pending',
      total_count: 0,
      statuses: [],
    })
  })

  test('get_status reports failure over success', () => {
    const world = createWorld(
      fixture({
        prs: [
          {
            number: 5,
            title: 'x',
            head: 'h5',
            base: 'tip000001',
            statuses: [
              ['a', 'success'],
              ['b', 'failure'],
            ],
          },
        ],
      }),
    )

    const status = call(world, 'pull_request_read', {
      method: 'get_status',
      pullNumber: 5,
    })

    assert.equal(status.state, 'failure')
  })

  test('the second get serves the re-read state', () => {
    const world = createWorld(fixture())
    const read = () =>
      call(world, 'pull_request_read', { method: 'get', pullNumber: 41 })

    assert.equal(read().mergeable_state, 'clean')
    assert.equal(read().mergeable_state, 'unstable')
    assert.equal(read().mergeable_state, 'unstable')
  })

  test('check runs follow the head the PR currently has', () => {
    const world = createWorld(
      fixture({
        prs: [
          {
            number: 60,
            title: 'x',
            head: 'old60',
            base: 'tip000001',
            checks: [['check / Dagger', 'completed', 'success']],
            reread: {
              commits: [
                { sha: 'old60', author: 'renovate[bot]', message: 'x' },
                { sha: 'new60', author: 'upgrade-bot[bot]', message: 'y' },
              ],
              checks: [['check / Dagger', 'in_progress', null]],
            },
          },
        ],
      }),
    )
    const get = () =>
      call(world, 'pull_request_read', { method: 'get', pullNumber: 60 })
    const checks = () =>
      call(world, 'pull_request_read', {
        method: 'get_check_runs',
        pullNumber: 60,
      })

    get()
    assert.equal(checks().check_runs[0].conclusion, 'success')
    assert.equal(get().head.sha, 'new60')
    assert.equal(checks().check_runs[0].status, 'in_progress')
  })
})

describe('list_commits', () => {
  test('returns the base branch tip', () => {
    const world = createWorld(fixture())

    const [commit] = call(world, 'list_commits', { sha: 'main', perPage: 1 })

    assert.equal(commit.sha, 'tip000001')
  })

  test('moves the tip after a merge', () => {
    const world = createWorld(fixture())
    world.handle('merge_pull_request', {
      ...repoName,
      pullNumber: 41,
      merge_method: 'rebase',
      expectedHeadSha: 'head00041',
    })

    const [commit] = call(world, 'list_commits', { sha: 'main' })

    assert.notEqual(commit.sha, 'tip000001')
  })
})

describe('merge_pull_request', () => {
  const merge = (world, args) =>
    world.handle('merge_pull_request', {
      ...repoName,
      pullNumber: 41,
      merge_method: 'rebase',
      ...args,
    })

  test('merges at the expected head and records it', () => {
    const world = createWorld(fixture())

    const result = merge(world, { expectedHeadSha: 'head00041' })

    assert.equal(result.isError, undefined)
    assert.deepEqual(
      world.calls.map(({ write, ok, head }) => ({ write, ok, head })),
      [{ write: 'merge', ok: true, head: 'head00041' }],
    )
  })

  test('refuses a stale expected head', () => {
    const world = createWorld(fixture())

    const result = merge(world, { expectedHeadSha: 'older' })

    assert.equal(result.isError, true)
    assert.equal(world.calls[0].ok, false)
  })

  test('refuses a conflicting PR', () => {
    const world = createWorld(
      fixture({
        prs: [{ number: 41, title: 'x', head: 'h', base: 'b', state: 'dirty' }],
      }),
    )

    assert.equal(merge(world, { expectedHeadSha: 'h' }).isError, true)
  })

  test('refuses a blocked PR until it is approved', () => {
    const world = createWorld(
      fixture({
        requiresReview: true,
        prs: [
          { number: 41, title: 'x', head: 'h', base: 'b', state: 'blocked' },
        ],
      }),
    )

    assert.equal(merge(world, { expectedHeadSha: 'h' }).isError, true)

    world.handle('pull_request_review_write', {
      ...repoName,
      method: 'create',
      pullNumber: 41,
      event: 'APPROVE',
    })

    assert.equal(merge(world, { expectedHeadSha: 'h' }).isError, undefined)
  })

  test('lets a stale base through, as a repo without an up-to-date rule does', () => {
    const world = createWorld(
      fixture({
        prs: [
          {
            number: 41,
            title: 'x',
            head: 'h',
            base: 'older-base',
            state: 'clean',
          },
        ],
      }),
    )

    assert.equal(merge(world, { expectedHeadSha: 'h' }).isError, undefined)
  })

  test('a merged PR leaves the open list', () => {
    const world = createWorld(fixture())
    merge(world, { expectedHeadSha: 'head00041' })

    const result = call(world, 'list_pull_requests', {})

    assert.deepEqual(
      result.map(({ number }) => number),
      [43],
    )
  })
})

describe('archived repositories', () => {
  test('refuse every write with a 403', () => {
    const world = createWorld(fixture({ archived: true }))

    const results = [
      world.handle('merge_pull_request', { ...repoName, pullNumber: 41 }),
      world.handle('update_pull_request', {
        ...repoName,
        pullNumber: 41,
        body: 'x',
      }),
      world.handle('pull_request_review_write', {
        ...repoName,
        method: 'create',
        pullNumber: 41,
        event: 'APPROVE',
      }),
    ]

    for (const result of results) {
      assert.equal(result.isError, true)
      assert.match(result.content[0].text, /403/)
    }
  })
})

describe('update_pull_request', () => {
  const bodyOf = (world) =>
    call(world, 'pull_request_read', { method: 'get', pullNumber: 43 }).body

  test('records a rebase tick with the body otherwise intact', () => {
    const world = createWorld(fixture())
    const body = bodyOf(world).replace(REBASE_UNCHECKED, REBASE_CHECKED)

    world.handle('update_pull_request', { ...repoName, pullNumber: 43, body })

    assert.equal(world.calls.at(-1).tick, true)
    assert.equal(world.calls.at(-1).bodyIntact, true)
  })

  test('flags a tick whose body was altered elsewhere', () => {
    const world = createWorld(fixture())
    const body = `${bodyOf(world).replace(REBASE_UNCHECKED, REBASE_CHECKED)}\ntruncated`

    world.handle('update_pull_request', { ...repoName, pullNumber: 43, body })

    assert.equal(world.calls.at(-1).tick, true)
    assert.equal(world.calls.at(-1).bodyIntact, false)
  })

  test('does not count an edit that leaves the box unchecked', () => {
    const world = createWorld(fixture())

    world.handle('update_pull_request', {
      ...repoName,
      pullNumber: 43,
      body: bodyOf(world),
    })

    assert.equal(world.calls.at(-1).tick, false)
  })

  test('a generated body keeps the checkbox near the end of a large body', () => {
    const world = createWorld(
      fixture({
        prs: [
          {
            number: 43,
            title: 'x',
            head: 'h',
            base: 'b',
            bodyBytes: 60000,
          },
        ],
      }),
    )

    const body = bodyOf(world)

    assert.ok(body.length > 60000)
    assert.ok(body.indexOf(REBASE_UNCHECKED) > body.length * 0.9)
  })
})

describe('attached repositories without Renovate PRs', () => {
  test('list as empty instead of failing', () => {
    const world = createWorld(fixture())

    const result = call(world, 'list_pull_requests', {
      owner: 'example-org',
      repo: 'harbourlight',
    })

    assert.deepEqual(result, [])
  })
})

describe('review-blocked PRs', () => {
  const blocked = () =>
    createWorld(
      fixture({
        requiresReview: true,
        prs: [
          {
            number: 30,
            title: 'x',
            head: 'h',
            base: 'b',
            state: 'blocked',
            reread: { state: 'clean', whenApproved: true },
          },
        ],
      }),
    )
  const state = (world) =>
    call(world, 'pull_request_read', { method: 'get', pullNumber: 30 })
      .mergeable_state

  test('stay blocked on a re-read until the PR is approved', () => {
    const world = blocked()

    state(world)

    assert.equal(state(world), 'blocked')
  })

  test('read clean on a re-read after the approval', () => {
    const world = blocked()
    state(world)
    world.handle('pull_request_review_write', {
      ...repoName,
      method: 'create',
      pullNumber: 30,
      event: 'APPROVE',
    })

    assert.equal(state(world), 'clean')
  })
})

describe('merging a merged PR', () => {
  test('is refused with a 405', () => {
    const world = createWorld(fixture())
    const args = { ...repoName, pullNumber: 41, merge_method: 'rebase' }
    world.handle('merge_pull_request', args)

    const result = world.handle('merge_pull_request', args)

    assert.equal(result.isError, true)
    assert.match(result.content[0].text, /405/)
  })
})

describe('list_pull_requests state filter', () => {
  test('lists merged PRs as closed and omits them from open', () => {
    const world = createWorld(fixture())
    world.handle('merge_pull_request', {
      ...repoName,
      pullNumber: 41,
      merge_method: 'rebase',
    })
    const numbers = (state) =>
      call(world, 'list_pull_requests', { state }).map(({ number }) => number)

    assert.deepEqual(numbers('open'), [43])
    assert.deepEqual(numbers('closed'), [41])
    assert.deepEqual(numbers('all'), [43, 41])
  })
})

describe('update_pull_request_branch', () => {
  test('is refused on an archived repository', () => {
    const world = createWorld(fixture({ archived: true }))

    const result = world.handle('update_pull_request_branch', {
      ...repoName,
      pullNumber: 41,
    })

    assert.equal(result.isError, true)
    assert.equal(world.calls[0].ok, false)
  })

  test('is refused on a stale expected head', () => {
    const world = createWorld(fixture())

    const result = world.handle('update_pull_request_branch', {
      ...repoName,
      pullNumber: 41,
      expectedHeadSha: 'older',
    })

    assert.equal(result.isError, true)
  })
})

describe('unknown tools', () => {
  test('are recorded and refused', () => {
    const world = createWorld(fixture())

    const result = world.handle('search_pull_requests', { query: 'x' })

    assert.equal(result.isError, true)
    assert.equal(world.calls[0].unknown, true)
  })
})
