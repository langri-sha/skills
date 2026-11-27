import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { referenceCalls } from './reference-run.js'
import { createWorld } from './world.js'
import { scoreCalls } from './score.js'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const { evals } = JSON.parse(readFileSync(join(root, 'evals.json'), 'utf8'))

for (const { id, files } of evals) {
  describe(`case ${id}`, () => {
    const { expect, ...world } = JSON.parse(
      readFileSync(join(root, files[0]), 'utf8'),
    )

    test('a run that does nothing fails', () => {
      const criteria = scoreCalls({ expect, calls: [], fixture: world })

      assert.ok(criteria.some(({ status }) => status === 'fail'))
    })

    test('a run of the correct calls fails no deterministic criterion', () => {
      const calls = referenceCalls({ expect, ...world })
      const failures = scoreCalls({ expect, calls, fixture: world }).filter(
        ({ status }) => status === 'fail',
      )

      assert.deepEqual(failures, [])
    })
  })
}

describe('case 11 when the run approves before the re-read', () => {
  const { expect, ...world } = JSON.parse(
    readFileSync(
      join(root, 'fixtures/11-head-moved-before-merge.json'),
      'utf8',
    ),
  )
  const target = { owner: 'langri-sha', repo: 'emberly', pullNumber: 60 }
  const run = (approveAfterMove, commitID) => {
    const live = createWorld(world)
    const get = () =>
      live.handle('pull_request_read', { ...target, method: 'get' })
    const approve = () =>
      live.handle('pull_request_review_write', {
        ...target,
        method: 'create',
        event: 'APPROVE',
        commitID,
      })

    live.handle('list_pull_requests', { ...target, pullNumber: undefined })
    get()
    live.handle('pull_request_read', { ...target, method: 'get_check_runs' })

    if (!approveAfterMove) {
      approve()
    }

    get()

    if (approveAfterMove) {
      approve()
    }

    return scoreCalls({ expect, calls: live.calls, fixture: world })
  }
  const statusOf = (criteria, id) => criteria.find((c) => c.id === id).status

  test('passes when the approval names the verified head', () => {
    const criteria = run(false)

    assert.equal(statusOf(criteria, 'writes.approved'), 'pass')
    assert.equal(statusOf(criteria, 'writes.approved_head:emberly#60'), 'pass')
  })

  test('fails when the approval lands on the moved head', () => {
    const criteria = run(true)

    assert.equal(statusOf(criteria, 'writes.approved_head:emberly#60'), 'fail')
  })

  test('fails when a re-read that saw the move is followed by an approval naming the old head', () => {
    const criteria = run(true, '5d4c3b2a1')

    assert.equal(statusOf(criteria, 'writes.approved_head:emberly#60'), 'fail')
  })
})
