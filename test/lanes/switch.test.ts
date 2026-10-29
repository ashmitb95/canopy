import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { readRepo } from '../../src/lanes/state'
import { joinRepo, moveIntoMain, moveToWorktree, SwitchError, worktreePath } from '../../src/lanes/switch'
import { repo, run, workspace } from './repos'

async function setup() {
  const root = workspace()
  const api = repo(join(root, 'api'))
  return { root, api, state: () => readRepo(root, api) }
}

const branchIn = (path: string) => run(path, 'branch', '--show-current').trim()

// Real git under full-suite load exceeds the default 5s.
describe('moveIntoMain', { timeout: 20_000 }, () => {
  it('swaps lanes, carrying each lane’s uncommitted work', async () => {
    const { api, state } = await setup()
    run(api, 'branch', 'a')
    run(api, 'worktree', 'add', '-q', join(api, '.worktrees', 'a'), 'a')
    run(api, 'checkout', '-q', '-b', 'b')
    writeFileSync(join(api, 'b-work.txt'), 'b')
    writeFileSync(join(api, '.worktrees', 'a', 'a-work.txt'), 'a')

    expect(await moveIntoMain(await state(), 'a')).toEqual({ movedOut: 'b', worktree: worktreePath(api, 'b') })
    expect(branchIn(api)).toBe('a')
    expect(readFileSync(join(api, 'a-work.txt'), 'utf8')).toBe('a')
    expect(existsSync(join(api, 'b-work.txt'))).toBe(false)
    expect(branchIn(worktreePath(api, 'b'))).toBe('b')
    expect(readFileSync(join(worktreePath(api, 'b'), 'b-work.txt'), 'utf8')).toBe('b')
    expect(existsSync(join(api, '.worktrees', 'a'))).toBe(false)
    expect(run(api, 'stash', 'list').trim()).toBe('')
  })

  it('checks out a parked lane, or creates it from base', async () => {
    const { api, state } = await setup()
    run(api, 'branch', 'parked')
    expect(await moveIntoMain(await state(), 'parked')).toEqual({})
    expect(branchIn(api)).toBe('parked')
    run(api, 'checkout', '-q', 'main')
    expect(await moveIntoMain(await state(), 'fresh')).toEqual({})
    expect(branchIn(api)).toBe('fresh')
  })

  it('refuses when main holds uncommitted work on the base branch', async () => {
    const { api, state } = await setup()
    writeFileSync(join(api, 'README.md'), 'changed')
    await expect(moveIntoMain(await state(), 'x')).rejects.toBeInstanceOf(SwitchError)
    expect(branchIn(api)).toBe('main')
  })
})

describe('moveToWorktree', { timeout: 20_000 }, () => {
  it('moves the lane out of main with its work and puts base back', async () => {
    const { api, state } = await setup()
    run(api, 'checkout', '-q', '-b', 'x')
    writeFileSync(join(api, 'x-work.txt'), 'x')
    expect(await moveToWorktree(await state(), 'x')).toBe(worktreePath(api, 'x'))
    expect(branchIn(api)).toBe('main')
    expect(existsSync(join(api, 'x-work.txt'))).toBe(false)
    expect(readFileSync(join(worktreePath(api, 'x'), 'x-work.txt'), 'utf8')).toBe('x')
  })

  it('makes a worktree for a parked lane and returns an existing one as is', async () => {
    const { api, state } = await setup()
    run(api, 'branch', 'p')
    const path = await moveToWorktree(await state(), 'p')
    expect(branchIn(path)).toBe('p')
    expect(await moveToWorktree(await state(), 'p')).toBe(path)
  })

  it('keeps .worktrees out of the repo’s status', async () => {
    const { api, state } = await setup()
    run(api, 'branch', 'p')
    await moveToWorktree(await state(), 'p')
    expect(run(api, 'status', '--porcelain').trim()).toBe('')
  })
})

describe('joinRepo', { timeout: 20_000 }, () => {
  it('starts the lane in a worktree from base', async () => {
    const { api, state } = await setup()
    const path = await joinRepo(await state(), 'feat/x', true)
    expect(path).toBe(join(api, '.worktrees', 'feat--x'))
    expect(branchIn(path)).toBe('feat/x')
  })

  it('starts the lane in main when worktrees are off and main is free', async () => {
    const { api, state } = await setup()
    expect(await joinRepo(await state(), 'y', false)).toBe(api)
    expect(branchIn(api)).toBe('y')
  })

  it('refuses main when another lane holds it', async () => {
    const { api, state } = await setup()
    run(api, 'checkout', '-q', '-b', 'other')
    await expect(joinRepo(await state(), 'y', false)).rejects.toThrow(/main checkout is busy/)
  })
})
