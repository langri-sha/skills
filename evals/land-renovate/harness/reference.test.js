import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { referenceCalls } from './reference-run.js'
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
