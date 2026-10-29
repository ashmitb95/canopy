import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { discoverRepos } from '../../src/lanes/discover'
import { parseWorktrees, readRepo } from '../../src/lanes/state'
import { repo, run, workspace } from './repos'

describe('parseWorktrees', () => {
  it('reads the main checkout first, branches, detached heads, and skips bare entries', () => {
    const text = [
      'worktree /w/api\nHEAD aaa\nbranch refs/heads/retry-fix\n',
      'worktree /w/api/.worktrees/auth\nHEAD bbb\nbranch refs/heads/feat/auth\n',
      'worktree /w/api/.worktrees/old\nHEAD ccc\ndetached\n',
      'worktree /w/bare\nbare\n'
    ].join('\n')
    expect(parseWorktrees(text)).toEqual([
      { path: '/w/api', main: true, branch: 'retry-fix' },
      { path: '/w/api/.worktrees/auth', main: false, branch: 'feat/auth' },
      { path: '/w/api/.worktrees/old', main: false }
    ])
  })
})

describe('discoverRepos', () => {
  it('finds repos under the root, skipping their insides and dependency folders', async () => {
    const root = workspace()
    repo(join(root, 'ui'))
    repo(join(root, 'services', 'api'))
    repo(join(root, 'ui', 'packages', 'nested'))
    mkdirSync(join(root, 'node_modules', 'dep'), { recursive: true })
    repo(join(root, 'node_modules', 'dep'))
    expect(await discoverRepos(root)).toEqual([join(root, 'services', 'api'), join(root, 'ui')])
  })

  it('is just the root when the root is a repo', async () => {
    const root = repo(workspace())
    repo(join(root, 'vendor-copy'))
    expect(await discoverRepos(root)).toEqual([root])
  })
})

describe('readRepo', () => {
  it('reads checkouts, the base branch, and uncommitted files', async () => {
    const root = workspace()
    const api = repo(join(root, 'api'))
    run(api, 'checkout', '-q', '-b', 'retry-fix')
    run(api, 'worktree', 'add', '-q', '-b', 'auth', join(api, '.worktrees', 'auth'))
    writeFileSync(join(api, 'a.ts'), 'a')
    writeFileSync(join(api, 'README.md'), 'changed')
    expect(await readRepo(root, api)).toEqual({
      path: api,
      name: 'api',
      base: 'main',
      checkouts: [
        { path: api, main: true, branch: 'retry-fix', dirty: 2 },
        { path: join(api, '.worktrees', 'auth'), main: false, branch: 'auth', dirty: 0 }
      ]
    })
  })

  it('takes the base branch from origin when there is one', async () => {
    const root = workspace()
    const origin = repo(join(root, 'origin'))
    run(origin, 'branch', '-q', '-m', 'trunk-line')
    run(root, 'clone', '-q', origin, join(root, 'clone'))
    expect((await readRepo(root, join(root, 'clone'))).base).toBe('trunk-line')
  })
})
