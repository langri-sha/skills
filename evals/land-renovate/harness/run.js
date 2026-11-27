#!/usr/bin/env node
import { execFileSync, spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import {
  appendFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { parseArgs } from 'node:util'
import { fileURLToPath } from 'node:url'

import {
  abstainJudgement,
  judgePrompt,
  parseJudgement,
  scoreCalls,
  tally,
} from './score.js'

const evalRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const mockServer = join(evalRoot, 'harness', 'mock-github.js')
const CANDIDATE_TOOLS = ['Read', 'Glob', 'Grep', 'ToolSearch']
const ALLOWED = ['mcp__github', 'ToolSearch']
const QUIET_REPOSITORIES = ['langri-sha/skills', 'example-org/harbourlight']
const MCP_TOOLS = /^mcp__github__/

const git = (cwd, ...args) =>
  execFileSync('git', args, { cwd, encoding: 'utf8' }).trim()

export const repoRootOf = (dir) => git(dir, 'rev-parse', '--show-toplevel')

export const pinSkill = (repoRoot, ref) => ({
  ref,
  commit: git(repoRoot, 'rev-parse', `${ref}^{commit}`),
  tree: git(repoRoot, 'rev-parse', `${ref}:land-renovate`),
})

export const buildWorkdir = ({ repoRoot, skillCommit, fixture, dir }) => {
  const checkout = join(dir, 'skills')

  mkdirSync(checkout, { recursive: true })
  execFileSync(
    'sh',
    ['-c', `git archive "${skillCommit}" | tar -x -C "${checkout}"`],
    { cwd: repoRoot },
  )
  rmSync(join(checkout, 'evals'), { recursive: true, force: true })

  const repos = [
    ...QUIET_REPOSITORIES.filter((name) => name !== 'langri-sha/skills').map(
      (name) => ({ name }),
    ),
    ...fixture.repos,
  ]

  for (const repo of repos) {
    const [owner, name] = repo.name.split('/')
    const root = join(dir, name)

    mkdirSync(join(root, '.git'), { recursive: true })
    writeFileSync(join(root, 'README.md'), `# ${name}\n`)
    writeFileSync(join(root, '.git', 'HEAD'), 'ref: refs/heads/main\n')
    writeFileSync(
      join(root, '.git', 'config'),
      `[remote "origin"]\n\turl = https://github.com/${owner}/${name}.git\n`,
    )

    for (const [path, content] of Object.entries(repo.files ?? {})) {
      mkdirSync(dirname(join(root, path)), { recursive: true })
      writeFileSync(join(root, path), content)
    }
  }

  return checkout
}

export const attachedRepositories = (fixture) => [
  ...QUIET_REPOSITORIES,
  ...fixture.repos.map(({ name }) => name),
]

export const attachedContext = (fixture) =>
  [
    'Repositories attached to this session, each checked out in its own directory under the working directory:',
    ...attachedRepositories(fixture).map(
      (name) => `- ${name} (${name.split('/')[1]}/)`,
    ),
  ].join('\n')

export const claudeArgs = ({ model, mcpConfig, maxBudget, attached }) => [
  '-p',
  '--model',
  model,
  '--output-format',
  'stream-json',
  '--verbose',
  '--no-session-persistence',
  '--setting-sources',
  'project',
  '--disable-slash-commands',
  '--strict-mcp-config',
  '--mcp-config',
  mcpConfig,
  '--tools',
  CANDIDATE_TOOLS.join(','),
  '--permission-mode',
  'dontAsk',
  '--allowedTools',
  ALLOWED.join(','),
  '--append-system-prompt',
  attached,
  '--max-budget-usd',
  String(maxBudget),
]

export const checkInit = (init) => {
  const problems = []
  const tools = init.tools ?? []
  const stray = tools.filter(
    (tool) => !CANDIDATE_TOOLS.includes(tool) && !MCP_TOOLS.test(tool),
  )

  if (stray.length > 0) {
    problems.push(`unexpected tools: ${stray}`)
  }

  const servers = (init.mcp_servers ?? []).map(({ name, status }) => ({
    name,
    status,
  }))

  if (
    servers.length !== 1 ||
    servers[0].name !== 'github' ||
    servers[0].status !== 'connected'
  ) {
    problems.push(`unexpected MCP servers: ${JSON.stringify(servers)}`)
  }

  const plugins = (init.plugins ?? []).filter(
    ({ source }) => !source?.endsWith('@builtin'),
  )

  if (plugins.length > 0) {
    problems.push(`unexpected plugins: ${plugins.map(({ name }) => name)}`)
  }

  for (const field of ['slash_commands', 'skills']) {
    if ((init[field] ?? []).length > 0) {
      problems.push(`unexpected ${field}: ${init[field].length}`)
    }
  }

  return problems
}

const candidateEnv = () => {
  const env = { ...process.env }

  for (const name of Object.keys(env)) {
    if (name.startsWith('CLAUDE_CODE_') || name === 'CLAUDECODE') {
      delete env[name]
    }
  }

  return {
    ...env,
    CLAUDE_CODE_DISABLE_AUTO_MEMORY: '1',
    CLAUDE_CODE_DISABLE_CLAUDE_MDS: '1',
    ENABLE_TOOL_SEARCH: 'true',
  }
}

const runClaude = ({ bin, args, cwd, env, input, timeoutMs }) =>
  new Promise((resolve) => {
    const child = spawn(bin, args, {
      cwd,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    let stdout = ''
    let stderr = ''
    const timer = setTimeout(() => child.kill('SIGKILL'), timeoutMs)

    child.stdout.on('data', (chunk) => (stdout += chunk))
    child.stderr.on('data', (chunk) => (stderr += chunk))
    child.on('close', (code) => {
      clearTimeout(timer)
      resolve({ code, stdout, stderr })
    })
    child.stdin.end(input)
  })

const events = (stdout) =>
  stdout
    .split('\n')
    .filter(Boolean)
    .flatMap((line) => {
      try {
        return [JSON.parse(line)]
      } catch {
        return []
      }
    })

const readCalls = (path) => {
  try {
    return readFileSync(path, 'utf8')
      .split('\n')
      .filter(Boolean)
      .map((line) => JSON.parse(line))
  } catch {
    return []
  }
}

const judge = async ({ bin, model, report, criteria, scratch }) => {
  if (criteria.length === 0) {
    return []
  }

  const result = await runClaude({
    bin,
    args: [
      '-p',
      '--model',
      model,
      '--output-format',
      'json',
      '--no-session-persistence',
      '--setting-sources',
      'project',
      '--disable-slash-commands',
      '--strict-mcp-config',
      '--mcp-config',
      '{"mcpServers":{}}',
      '--tools',
      '',
      '--max-budget-usd',
      '0.25',
    ],
    cwd: scratch,
    env: candidateEnv(),
    input: judgePrompt({ report, criteria }),
    timeoutMs: 5 * 60 * 1000,
  })

  try {
    return parseJudgement(JSON.parse(result.stdout).result ?? '', criteria)
  } catch {
    return abstainJudgement(
      criteria,
      `judge failed: ${result.stderr.slice(0, 200)}`,
    )
  }
}

const replayCase = async ({
  entry,
  options,
  runDir,
  pin,
  prompt,
  work,
  mockDir,
}) => {
  const fixture = JSON.parse(
    readFileSync(join(evalRoot, entry.files[0]), 'utf8'),
  )
  const { expect, ...world } = fixture
  const caseDir = join(runDir, String(entry.id).padStart(2, '0'))
  const fixturePath = join(mockDir, 'fixture.json')
  const callsPath = join(caseDir, 'calls.jsonl')

  mkdirSync(caseDir, { recursive: true })
  writeFileSync(fixturePath, JSON.stringify(world))

  const cwd = buildWorkdir({
    repoRoot: options.repoRoot,
    skillCommit: pin.commit,
    fixture,
    dir: work,
  })
  const mcpConfig = JSON.stringify({
    mcpServers: {
      github: {
        command: process.execPath,
        args: [mockServer],
        env: { MOCK_FIXTURE: fixturePath, MOCK_CALLS: callsPath },
      },
    },
  })
  const started = Date.now()
  const run = await runClaude({
    bin: options.claude,
    args: claudeArgs({
      model: options.model,
      mcpConfig,
      maxBudget: options.maxBudget,
      attached: attachedContext(fixture),
    }),
    cwd: work,
    env: candidateEnv(),
    input: prompt,
    timeoutMs: 15 * 60 * 1000,
  })

  writeFileSync(join(caseDir, 'transcript.jsonl'), run.stdout)
  writeFileSync(join(caseDir, 'stderr.txt'), run.stderr)

  const stream = events(run.stdout)
  const init = stream.find(
    ({ type, subtype }) => type === 'system' && subtype === 'init',
  )
  const final = stream.findLast(({ type }) => type === 'result')
  const problems = init ? checkInit(init) : ['no init event']
  const calls = readCalls(callsPath)
  const report = final?.result ?? ''

  writeFileSync(join(caseDir, 'report.md'), report)

  const meta = {
    id: entry.id,
    exitCode: run.code,
    seconds: Math.round((Date.now() - started) / 1000),
    turns: final?.num_turns,
    costUsd: final?.total_cost_usd,
    usage: final?.usage,
    isError: final?.is_error ?? true,
    isolation: problems,
    cwd,
  }

  writeFileSync(join(caseDir, 'meta.json'), JSON.stringify(meta, null, 2))

  if (problems.length > 0 || !final || final.is_error) {
    const detail = problems.length > 0 ? problems.join('; ') : 'run failed'

    return {
      id: entry.id,
      error: detail,
      criteria: [],
      counts: null,
      meta,
    }
  }

  const deterministic = scoreCalls({ expect, calls, fixture: world })
  const judged = options.judge
    ? await judge({
        bin: options.claude,
        model: options.judgeModel,
        report,
        criteria: expect.report ?? [],
        scratch: work,
      })
    : abstainJudgement(expect.report ?? [])
  const criteria = [...deterministic, ...judged]

  writeFileSync(join(caseDir, 'score.json'), JSON.stringify(criteria, null, 2))

  return { id: entry.id, criteria, counts: tally(criteria), meta }
}

const runCase = async (context) => {
  const parent = mkdtempSync(join(tmpdir(), 'land-renovate-'))
  const work = join(parent, 'work')
  const mockDir = join(parent, 'mock')

  mkdirSync(work)
  mkdirSync(mockDir)

  try {
    return await replayCase({ ...context, work, mockDir })
  } finally {
    rmSync(parent, { recursive: true, force: true })
  }
}

export const summarize = (results) =>
  results
    .map(({ id, error, counts, criteria }) => {
      if (error) {
        return `case ${id}: ERROR ${error}`
      }

      const failures = criteria
        .filter(({ status }) => status === 'fail')
        .map(({ id: name, detail }) => `${name}${detail ? ` (${detail})` : ''}`)
      const abstentions = criteria
        .filter(({ status }) => status === 'abstain')
        .map(({ id: name }) => name)

      return [
        `case ${id}: ${counts.pass} pass, ${counts.fail} fail, ${counts.abstain} abstain, ${counts.na} n/a`,
        ...failures.map((failure) => `  FAIL ${failure}`),
        ...abstentions.map((name) => `  ABSTAIN ${name}`),
      ].join('\n')
    })
    .join('\n')

const main = async () => {
  const { values } = parseArgs({
    options: {
      cases: { type: 'string' },
      model: { type: 'string', default: 'claude-sonnet-5-5' },
      'judge-model': { type: 'string', default: 'claude-haiku-5-5' },
      prompt: { type: 'string', default: join(evalRoot, 'prompts', 'v5.txt') },
      'skill-ref': { type: 'string', default: 'origin/main' },
      out: { type: 'string' },
      claude: { type: 'string', default: process.env.CLAUDE_BIN ?? 'claude' },
      'max-budget-usd': { type: 'string', default: '2' },
      'no-judge': { type: 'boolean', default: false },
    },
  })
  const repoRoot = repoRootOf(evalRoot)
  const { evals } = JSON.parse(
    readFileSync(join(evalRoot, 'evals.json'), 'utf8'),
  )
  const wanted = values.cases?.split(',').map(Number)
  const selected = evals.filter(({ id }) => !wanted || wanted.includes(id))
  const prompt = readFileSync(values.prompt, 'utf8')
  const runId = new Date().toISOString().replace(/[:.]/g, '-')
  const runDir = values.out ?? join(tmpdir(), 'land-renovate-evals', runId)
  const pin = pinSkill(repoRoot, values['skill-ref'])
  const options = {
    repoRoot,
    claude: values.claude,
    model: values.model,
    judgeModel: values['judge-model'],
    judge: !values['no-judge'],
    maxBudget: Number(values['max-budget-usd']),
  }

  mkdirSync(runDir, { recursive: true })

  const receipt = {
    runId,
    startedAt: new Date().toISOString(),
    model: options.model,
    judgeModel: options.judge ? options.judgeModel : null,
    claude: execFileSync(options.claude, ['--version'], {
      encoding: 'utf8',
    }).trim(),
    skill: pin,
    prompt: {
      path: values.prompt,
      sha256: createHash('sha256').update(prompt).digest('hex'),
    },
    harness: {
      commit: git(repoRoot, 'rev-parse', 'HEAD'),
      dirty: git(repoRoot, 'status', '--porcelain', '--', 'evals').length > 0,
    },
    settings: {
      liveTools: false,
      builtinTools: CANDIDATE_TOOLS,
      allowed: ALLOWED,
      mcp: 'mock github, 7 tools, no search_pull_requests',
      attachedRepositoriesInSystemPrompt: true,
      permissionMode: 'dontAsk',
      settingSources: 'project',
      maxBudgetUsdPerCase: options.maxBudget,
    },
    cases: selected.map(({ id }) => id),
  }

  writeFileSync(join(runDir, 'receipt.json'), JSON.stringify(receipt, null, 2))

  const results = []

  for (const entry of selected) {
    const result = await runCase({
      entry,
      options,
      runDir,
      pin,
      prompt,
    })

    results.push(result)
    appendFileSync(join(runDir, 'results.jsonl'), `${JSON.stringify(result)}\n`)
    process.stdout.write(`${summarize([result])}\n`)
  }

  writeFileSync(join(runDir, 'summary.txt'), `${summarize(results)}\n`)
  process.stdout.write(`\nresults: ${runDir}\n`)
}

if (import.meta.url === `file://${process.argv[1]}`) {
  await main()
}
