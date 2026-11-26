import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, describe, test } from 'node:test'

import {
  buildWorkdir,
  checkInit,
  attachedContext,
  claudeArgs,
  pinSkill,
  repoRootOf,
  summarize,
} from './run.js'

const repoRoot = repoRootOf(import.meta.dirname)

const cleanInit = {
  tools: [
    'Read',
    'Glob',
    'Grep',
    'ToolSearch',
    'mcp__github__merge_pull_request',
  ],
  mcp_servers: [{ name: 'github', status: 'connected' }],
  slash_commands: [],
  skills: [],
  plugins: [],
  agents: [],
}

describe('claudeArgs', () => {
  const args = claudeArgs({ model: 'm', mcpConfig: '{}', maxBudget: 2 })

  test('leaves out shell, write and web tools', () => {
    const tools = args[args.indexOf('--tools') + 1].split(',')

    assert.deepEqual(tools, ['Read', 'Glob', 'Grep', 'ToolSearch'])
  })

  test('names the attached repositories in the system prompt', () => {
    const flagged = claudeArgs({
      model: 'm',
      mcpConfig: '{}',
      maxBudget: 2,
      attached: 'attached text',
    })

    assert.equal(
      flagged[flagged.indexOf('--append-system-prompt') + 1],
      'attached text',
    )
  })

  test('uses only the supplied MCP config', () => {
    assert.ok(args.includes('--strict-mcp-config'))
  })

  test('denies whatever is not allowed instead of prompting', () => {
    assert.equal(args[args.indexOf('--permission-mode') + 1], 'dontAsk')
  })

  test('leaves reading to the default permission, so it stays in the working directory', () => {
    const allowed = args[args.indexOf('--allowedTools') + 1].split(',')

    assert.deepEqual(allowed, ['mcp__github', 'ToolSearch'])
  })

  test('caps spend per case', () => {
    assert.equal(args[args.indexOf('--max-budget-usd') + 1], '2')
  })
})

describe('checkInit', () => {
  test('accepts the expected isolated session', () => {
    assert.deepEqual(checkInit(cleanInit), [])
  })

  test('rejects a shell tool', () => {
    assert.match(
      checkInit({ ...cleanInit, tools: [...cleanInit.tools, 'Bash'] })[0],
      /Bash/,
    )
  })

  test('rejects an MCP server that is not the mock', () => {
    const problems = checkInit({
      ...cleanInit,
      mcp_servers: [{ name: 'github', status: 'failed' }],
    })

    assert.equal(problems.length, 1)
  })

  test('accepts built-in plugins and agents', () => {
    const problems = checkInit({
      ...cleanInit,
      plugins: [
        { name: 'cc-plugin-privacy', source: 'cc-plugin-privacy@builtin' },
      ],
      agents: ['claude', 'Explore'],
    })

    assert.deepEqual(problems, [])
  })

  test('rejects loaded skills and plugins', () => {
    const problems = checkInit({
      ...cleanInit,
      skills: ['create-pr'],
      plugins: [{ name: 'posthog', source: 'posthog@marketplace' }],
    })

    assert.equal(problems.length, 2)
  })
})

describe('attachedContext', () => {
  const fixture = { repos: [{ name: 'langri-sha/glassfrog' }] }

  test('lists the session repositories with the fixture repositories', () => {
    assert.equal(
      attachedContext(fixture),
      [
        'Repositories attached to this session, each checked out in its own directory under the working directory:',
        '- langri-sha/skills (skills/)',
        '- example-org/harbourlight (harbourlight/)',
        '- langri-sha/glassfrog (glassfrog/)',
      ].join('\n'),
    )
  })
})

describe('pinSkill', () => {
  test('pins the commit and the land-renovate tree', () => {
    const pin = pinSkill(repoRoot, 'HEAD')

    assert.match(pin.commit, /^[0-9a-f]{40}$/)
    assert.match(pin.tree, /^[0-9a-f]{40}$/)
  })
})

describe('buildWorkdir', () => {
  const fixture = {
    repos: [
      {
        name: 'langri-sha/glassfrog',
        files: { 'terraform/versions.tf': 'required_version = "~> 1.17.0"\n' },
        prs: [],
      },
    ],
  }
  const dir = mkdtempSync(join(tmpdir(), 'workdir-test-'))

  after(() => rmSync(dir, { recursive: true, force: true }))

  const checkout = buildWorkdir({
    repoRoot,
    skillCommit: pinSkill(repoRoot, 'HEAD').commit,
    fixture,
    dir,
  })

  test('checks out the skill', () => {
    assert.ok(existsSync(join(checkout, 'land-renovate', 'SKILL.md')))
  })

  test('keeps the rubrics out of the candidate checkout', () => {
    assert.equal(existsSync(join(checkout, 'evals')), false)
  })

  test('attaches the quiet session repositories', () => {
    assert.ok(existsSync(join(dir, 'harbourlight', 'README.md')))
  })

  test('attaches each fixture repository with its files', () => {
    assert.equal(
      readFileSync(join(dir, 'glassfrog', 'terraform', 'versions.tf'), 'utf8'),
      'required_version = "~> 1.17.0"\n',
    )
    assert.match(
      readFileSync(join(dir, 'glassfrog', '.git', 'config'), 'utf8'),
      /langri-sha\/glassfrog/,
    )
  })
})

describe('summarize', () => {
  test('lists failures and abstentions under their case', () => {
    const text = summarize([
      {
        id: 3,
        counts: { pass: 4, fail: 1, abstain: 1, na: 2 },
        criteria: [
          { id: 'writes.merged', status: 'fail', detail: 'extra [a#1]' },
          { id: 'report.1', status: 'abstain' },
        ],
      },
      { id: 4, error: 'no init event' },
    ])

    assert.match(text, /case 3: 4 pass, 1 fail, 1 abstain, 2 n\/a/)
    assert.match(text, /FAIL writes\.merged \(extra \[a#1\]\)/)
    assert.match(text, /ABSTAIN report\.1/)
    assert.match(text, /case 4: ERROR no init event/)
  })
})
