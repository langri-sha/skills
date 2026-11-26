import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createInterface } from 'node:readline'
import { after, test } from 'node:test'
import { fileURLToPath } from 'node:url'

const server = fileURLToPath(new URL('./mock-github.js', import.meta.url))

const directories = []

after(() => {
  for (const dir of directories) {
    rmSync(dir, { recursive: true, force: true })
  }
})

const startServer = () => {
  const dir = mkdtempSync(join(tmpdir(), 'mock-github-'))

  directories.push(dir)
  const fixturePath = join(dir, 'fixture.json')
  const callsPath = join(dir, 'calls.jsonl')

  writeFileSync(
    fixturePath,
    JSON.stringify({
      repos: [
        {
          name: 'langri-sha/quillstone',
          tip: 'tip1',
          prs: [{ number: 1, title: 'x', head: 'h1', base: 'tip1' }],
        },
      ],
    }),
  )

  const child = spawn('node', [server], {
    env: { ...process.env, MOCK_FIXTURE: fixturePath, MOCK_CALLS: callsPath },
    stdio: ['pipe', 'pipe', 'inherit'],
  })
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]()
  let id = 0

  const request = async (method, params) => {
    child.stdin.write(
      `${JSON.stringify({ jsonrpc: '2.0', id: ++id, method, params })}\n`,
    )
    return JSON.parse((await lines.next()).value)
  }

  return { child, request, callsPath }
}

test('speaks MCP over stdio: initialize, list tools, call a tool', async () => {
  const { child, request, callsPath } = startServer()

  try {
    const init = await request('initialize', { protocolVersion: '2025-06-18' })
    const { result } = await request('tools/list', {})
    const call = await request('tools/call', {
      name: 'pull_request_read',
      arguments: {
        method: 'get',
        owner: 'langri-sha',
        repo: 'quillstone',
        pullNumber: 1,
      },
    })

    assert.equal(init.result.serverInfo.name, 'github')
    assert.deepEqual(
      result.tools.map(({ name }) => name),
      [
        'list_pull_requests',
        'pull_request_read',
        'list_commits',
        'pull_request_review_write',
        'merge_pull_request',
        'update_pull_request',
        'update_pull_request_branch',
      ],
    )
    assert.equal(JSON.parse(call.result.content[0].text).number, 1)
    assert.equal(
      JSON.parse(readFileSync(callsPath, 'utf8').trim()).tool,
      'pull_request_read',
    )
  } finally {
    child.kill()
  }
})

test('does not expose search_pull_requests', async () => {
  const { child, request } = startServer()

  try {
    await request('initialize', {})
    const { result } = await request('tools/list', {})

    assert.ok(!result.tools.some(({ name }) => name === 'search_pull_requests'))
  } finally {
    child.kill()
  }
})
