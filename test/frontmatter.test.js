import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, test } from 'node:test'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const directoriesThatAreNotSkills = new Set(['node_modules', 'test'])
const allowedFields = new Set([
  'name',
  'description',
  'metadata',
  'license',
  'argument-hint',
  'disable-model-invocation',
])

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

const filesOf = (directory) =>
  readdirSync(join(root, directory), { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => join(entry.parentPath, entry.name).slice(root.length))

const markdownFilesOf = (directory) =>
  filesOf(directory).filter((path) => path.endsWith('.md'))

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

      test('uses only the frontmatter fields the house style allows', () => {
        for (const field of fieldsOf(directory).keys()) {
          assert.ok(allowedFields.has(field), `${field} is not allowed`)
        }
      })

      test('keeps argument-hint at the top level, where Claude Code reads it', () => {
        assert.doesNotMatch(
          frontmatterBlock(readSkill(directory)) ?? '',
          /^[ \t]+argument-hint:/m,
        )
      })

      test('keeps SKILL.md within 500 lines', () => {
        const lines = readSkill(directory).trimEnd().split('\n').length

        assert.ok(lines <= 500, `${lines} lines`)
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

      test('keeps angle brackets out of its description', () => {
        assert.doesNotMatch(
          fieldsOf(directory).get('description') ?? '',
          /[<>]/,
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

      test('names bundled files by the skill directory, not an install path', () => {
        for (const file of filesOf(directory)) {
          assert.doesNotMatch(
            readFileSync(join(root, file), 'utf8'),
            /~\/\.claude\/skills/,
            file,
          )
        }
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
