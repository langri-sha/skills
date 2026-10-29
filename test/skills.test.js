import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, test } from 'node:test'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const directoriesThatAreNotSkills = new Set(['node_modules', 'test'])

const skillDirectories = readdirSync(root, { withFileTypes: true })
  .filter(
    (entry) =>
      entry.isDirectory() &&
      !entry.name.startsWith('.') &&
      !directoriesThatAreNotSkills.has(entry.name),
  )
  .map((entry) => entry.name)

const frontmatterName = (directory) => {
  const skill = readFileSync(join(root, directory, 'SKILL.md'), 'utf8')
  const [, frontmatter = ''] = skill.split(/^---$/m)

  return frontmatter.match(/^name:\s*['"]?([^'"\n]+?)['"]?\s*$/m)?.[1]
}

describe('skill discovery', () => {
  test('the repository root is not a skill itself', () => {
    assert.equal(existsSync(join(root, 'SKILL.md')), false)
  })

  for (const directory of ['skills', '.agents/skills', '.claude/skills']) {
    test(`${directory} does not exist to shadow the top-level skills`, () => {
      assert.equal(existsSync(join(root, directory)), false)
    })
  }
})

describe('top-level directories', () => {
  test('are found', () => {
    assert.ok(skillDirectories.length > 0)
  })

  for (const directory of skillDirectories) {
    test(`${directory} is a skill named after its directory`, () => {
      assert.equal(frontmatterName(directory), directory)
    })
  }
})
