import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { createWorld } from './world.js'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const { skill_name: skillName, evals } = JSON.parse(
  readFileSync(join(root, 'evals.json'), 'utf8'),
)
const prIds = (fixture) =>
  fixture.repos.flatMap((repo) =>
    repo.prs.map((pr) => `${repo.name.split('/')[1]}#${pr.number}`),
  )
const referenced = (expect) =>
  [
    ...(expect.merged ?? []),
    ...(expect.ticked ?? []),
    ...(expect.approved ?? []),
    ...(expect.noChecksRead ?? []),
    ...(expect.settledByStatus ?? []),
  ].flat()

test('the cases belong to land-renovate', () => {
  assert.equal(skillName, 'land-renovate')
})

test('case ids run from 1 without gaps', () => {
  assert.deepEqual(
    evals.map(({ id }) => id),
    evals.map((_, index) => index + 1),
  )
})

for (const { id, prompt, expected_output: rubric, files } of evals) {
  describe(`case ${id}`, () => {
    const [file] = files
    const fixture = JSON.parse(readFileSync(join(root, file), 'utf8'))

    test('has a prompt, a rubric and exactly one fixture', () => {
      assert.ok(prompt.length > 0)
      assert.ok(rubric.length > 0)
      assert.equal(files.length, 1)
    })

    test('its fixture file is numbered after the case', () => {
      assert.match(
        file,
        new RegExp(`^fixtures/${String(id).padStart(2, '0')}-`),
      )
    })

    test('builds a world whose PRs can all be listed', () => {
      const world = createWorld(fixture)

      for (const repo of fixture.repos) {
        const [owner, name] = repo.name.split('/')
        const result = world.handle('list_pull_requests', {
          owner,
          repo: name,
        })

        assert.equal(JSON.parse(result.content[0].text).length, repo.prs.length)
      }
    })

    test('only expects outcomes for PRs that exist', () => {
      const known = new Set(prIds(fixture))

      for (const reference of referenced(fixture.expect)) {
        assert.ok(known.has(reference), reference)
      }
    })

    test('has report criteria for the judge', () => {
      assert.ok(fixture.expect.report.length > 0)
    })

    test('keeps every repository under langri-sha', () => {
      for (const { name } of fixture.repos) {
        assert.equal(name.split('/')[0], 'langri-sha')
      }
    })
  })
}
