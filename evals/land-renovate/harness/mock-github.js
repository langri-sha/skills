#!/usr/bin/env node
import { appendFileSync, readFileSync } from 'node:fs'
import { createInterface } from 'node:readline'

import { createWorld } from './world.js'

const repoArgs = {
  owner: { type: 'string' },
  repo: { type: 'string' },
}

const pageArgs = {
  perPage: { type: 'number' },
  page: { type: 'number' },
}

const tool = (name, description, properties, required) => ({
  name,
  description,
  inputSchema: {
    type: 'object',
    properties: { ...repoArgs, ...properties },
    required: ['owner', 'repo', ...required],
  },
})

export const TOOLS = [
  tool(
    'list_pull_requests',
    'List pull requests in a GitHub repository.',
    {
      state: { type: 'string', enum: ['open', 'closed', 'all'] },
      base: { type: 'string' },
      head: { type: 'string' },
      sort: { type: 'string' },
      direction: { type: 'string', enum: ['asc', 'desc'] },
      ...pageArgs,
    },
    [],
  ),
  tool(
    'pull_request_read',
    'Get information on a specific pull request in a GitHub repository. Methods: get, get_diff, get_status, get_files, get_review_comments, get_reviews, get_comments, get_check_runs.',
    {
      method: {
        type: 'string',
        enum: [
          'get',
          'get_diff',
          'get_status',
          'get_files',
          'get_review_comments',
          'get_reviews',
          'get_comments',
          'get_check_runs',
        ],
      },
      pullNumber: { type: 'number' },
      ...pageArgs,
    },
    ['method', 'pullNumber'],
  ),
  tool(
    'list_commits',
    'Get a list of commits of a branch in a GitHub repository.',
    { sha: { type: 'string' }, author: { type: 'string' }, ...pageArgs },
    [],
  ),
  tool(
    'pull_request_review_write',
    'Create, submit or delete a review on a pull request.',
    {
      method: {
        type: 'string',
        enum: ['create', 'submit_pending', 'delete_pending'],
      },
      pullNumber: { type: 'number' },
      body: { type: 'string' },
      event: {
        type: 'string',
        enum: ['APPROVE', 'REQUEST_CHANGES', 'COMMENT'],
      },
      commitID: { type: 'string' },
    },
    ['method', 'pullNumber'],
  ),
  tool(
    'merge_pull_request',
    'Merge a pull request in a GitHub repository.',
    {
      pullNumber: { type: 'number' },
      merge_method: { type: 'string', enum: ['merge', 'squash', 'rebase'] },
      commit_title: { type: 'string' },
      commit_message: { type: 'string' },
      expectedHeadSha: {
        type: 'string',
        description: 'Fail the merge unless the head is this SHA.',
      },
    },
    ['pullNumber'],
  ),
  tool(
    'update_pull_request',
    'Update an existing pull request in a GitHub repository.',
    {
      pullNumber: { type: 'number' },
      title: { type: 'string' },
      body: { type: 'string' },
      state: { type: 'string', enum: ['open', 'closed'] },
      base: { type: 'string' },
      draft: { type: 'boolean' },
    },
    ['pullNumber'],
  ),
  tool(
    'update_pull_request_branch',
    'Update the branch of a pull request with the latest changes from the base branch, by merging.',
    { pullNumber: { type: 'number' }, expectedHeadSha: { type: 'string' } },
    ['pullNumber'],
  ),
]

export const serve = ({ fixturePath, callsPath, input, output }) => {
  const world = createWorld(JSON.parse(readFileSync(fixturePath, 'utf8')))
  let flushed = 0

  const flush = () => {
    for (const call of world.calls.slice(flushed)) {
      appendFileSync(callsPath, `${JSON.stringify(call)}\n`)
    }

    flushed = world.calls.length
  }

  const send = (message) => output.write(`${JSON.stringify(message)}\n`)

  const respond = (message) => {
    const { id, method, params } = message

    if (method === 'initialize') {
      return send({
        jsonrpc: '2.0',
        id,
        result: {
          protocolVersion: params?.protocolVersion ?? '2025-06-18',
          capabilities: { tools: {} },
          serverInfo: { name: 'github', version: '0.0.0-mock' },
        },
      })
    }

    if (method === 'tools/list') {
      return send({ jsonrpc: '2.0', id, result: { tools: TOOLS } })
    }

    if (method === 'tools/call') {
      const result = world.handle(params.name, params.arguments ?? {})
      flush()
      return send({ jsonrpc: '2.0', id, result })
    }

    if (method === 'ping') {
      return send({ jsonrpc: '2.0', id, result: {} })
    }

    if (id !== undefined) {
      return send({
        jsonrpc: '2.0',
        id,
        error: { code: -32601, message: `method not found: ${method}` },
      })
    }
  }

  createInterface({ input }).on('line', (line) => {
    if (line.trim()) {
      respond(JSON.parse(line))
    }
  })
}

if (import.meta.url === `file://${process.argv[1]}`) {
  serve({
    fixturePath: process.env.MOCK_FIXTURE,
    callsPath: process.env.MOCK_CALLS,
    input: process.stdin,
    output: process.stdout,
  })
}
