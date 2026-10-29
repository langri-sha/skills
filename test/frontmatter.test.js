import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
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

const readSkill = (directory) =>
  readFileSync(join(root, directory, 'SKILL.md'), 'utf8')

const frontmatterBlock = (skill) => skill.match(/^---\n([\s\S]*?)\n---\n/)?.[1]

const scalarValue = ([first, ...continuation]) => {
  const head = /^[>|][+-]?$/.test(first)
    ? ''
    : first.replace(/^(['"])(.*)\1$/, '$2')

  return [head, ...continuation].filter(Boolean).join(' ')
}

const topLevelFields = (block) => {
  const lines = new Map()
  let current

  for (const line of block.split('\n')) {
    const field = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/)

    if (field) {
      current = field[1]
      lines.set(current, [field[2]])
    } else if (current) {
      lines.get(current).push(line.trim())
    }
  }

  return new Map([...lines].map(([key, value]) => [key, scalarValue(value)]))
}

const fieldsOf = (directory) =>
  topLevelFields(frontmatterBlock(readSkill(directory)) ?? '')

const markdownFilesOf = (directory) =>
  readdirSync(join(root, directory), { recursive: true })
    .filter((path) => path.endsWith('.md'))
    .map((path) => join(directory, path))

const relativeLinkTargets = (markdown) =>
  [...markdown.matchAll(/\]\(([^)\s#]+)(?:#[^)]*)?\)/g)]
    .map((match) => match[1])
    .filter((target) => !/^[a-z]+:/i.test(target))

const implicitInvocationDisabledForCodex = (directory) => {
  const policy = join(root, directory, 'agents', 'openai.yaml')

  return (
    existsSync(policy) &&
    /^\s*allow_implicit_invocation:\s*false\s*$/m.test(
      readFileSync(policy, 'utf8'),
    )
  )
}

describe('skill frontmatter', () => {
  for (const directory of skillDirectories) {
    describe(directory, () => {
      test('opens SKILL.md with a frontmatter block', () => {
        assert.ok(frontmatterBlock(readSkill(directory)))
      })

      test('has a lowercase, hyphenated name of at most 64 characters', () => {
        const name = fieldsOf(directory).get('name') ?? ''

        assert.match(name, /^[a-z0-9]+(?:-[a-z0-9]+)*$/)
        assert.ok(name.length <= 64)
      })

      test('has a description of at most 1024 characters', () => {
        const description = fieldsOf(directory).get('description') ?? ''

        assert.ok(description.length > 0)
        assert.ok(
          description.length <= 1024,
          `${description.length} characters`,
        )
      })

      test('stops implicit invocation on both harnesses or on neither', () => {
        const manualOnlyForClaude =
          fieldsOf(directory).get('disable-model-invocation') === 'true'

        assert.equal(
          implicitInvocationDisabledForCodex(directory),
          manualOnlyForClaude,
        )
      })

      test('links only to files it ships', () => {
        for (const file of markdownFilesOf(directory)) {
          for (const target of relativeLinkTargets(
            readFileSync(join(root, file), 'utf8'),
          )) {
            assert.ok(
              existsSync(join(root, dirname(file), target)),
              `${file} links to ${target}`,
            )
          }
        }
      })
    })
  }
})
