import { REBASE_CHECKED, REBASE_UNCHECKED } from './body.js'
import { createWorld } from './world.js'

const read = (world, owner, repo, pullNumber, method) =>
  JSON.parse(
    world.handle('pull_request_read', { owner, repo, pullNumber, method })
      .content[0].text,
  )

export const referenceCalls = ({ expect, ...fixture }) => {
  const world = createWorld(fixture)
  const settled = new Set(expect.settledByStatus ?? [])
  const skipped = new Set(expect.noChecksRead ?? [])
  const merged = new Set(expect.merged ?? [])
  const ticked = new Set(expect.ticked ?? [])
  const approved = new Set(expect.approved ?? [])

  for (const repository of fixture.repos) {
    const [owner, repo] = repository.name.split('/')
    const numbers = repository.prs
      .map(({ number }) => number)
      .sort((a, b) => a - b)

    world.handle('list_pull_requests', {
      owner,
      repo,
      state: 'open',
      direction: 'asc',
    })

    if (repository.archived) {
      read(world, owner, repo, numbers[0], 'get')
      continue
    }

    world.handle('list_commits', { owner, repo, sha: 'main', perPage: 1 })

    for (const number of numbers) {
      const id = `${repo}#${number}`

      if (skipped.has(id)) {
        continue
      }

      read(world, owner, repo, number, 'get_status')

      if (!settled.has(id)) {
        read(world, owner, repo, number, 'get')
        read(world, owner, repo, number, 'get_check_runs')
      }
    }

    for (const number of numbers) {
      const id = `${repo}#${number}`

      if (approved.has(id)) {
        world.handle('pull_request_review_write', {
          owner,
          repo,
          method: 'create',
          pullNumber: number,
          event: 'APPROVE',
        })
      }

      if (merged.has(id)) {
        const { head } = read(world, owner, repo, number, 'get')

        world.handle('merge_pull_request', {
          owner,
          repo,
          pullNumber: number,
          merge_method: 'rebase',
          expectedHeadSha: head.sha,
        })
      }

      if (ticked.has(id)) {
        const { body } = read(world, owner, repo, number, 'get')

        world.handle('update_pull_request', {
          owner,
          repo,
          pullNumber: number,
          body: body.replace(REBASE_UNCHECKED, REBASE_CHECKED),
        })
      }
    }
  }

  return world.calls
}
