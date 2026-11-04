import { execFileSync } from 'node:child_process'
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeEach, describe, expect, it } from 'vitest'
import { repo as makeRepo, run, workspace } from './repos'
import { git } from '../../src/lanes/git'
import { ALL_STEPS, commit, joinRepo, migrateToSlots, moveToWorktree, newLane, park, preflight, readJournal, rollback, swap, swapAll, SwitchQuestion, worktrees } from '../../src/lanes/switch'

let repo: string

const write = (dir: string, name: string, text: string) => writeFileSync(join(dir, name), text)
const read = (dir: string, name: string) => readFileSync(join(dir, name), 'utf8')
const status = (dir: string) => run(dir, 'status', '--porcelain').trim()
const branchOf = (dir: string) => run(dir, 'branch', '--show-current').trim()
const stashes = (dir: string) => run(dir, 'stash', 'list').trim()
const refs = (dir: string) => run(dir, 'for-each-ref', 'refs/canopy').trim()

function ignoreWorktrees(dir: string): void {
  writeFileSync(join(dir, '.git/info/exclude'), '.worktrees/\n')
}

/** Commits a lane branch with its own file, returning to where it was. */
function branch(dir: string, name: string): void {
  const back = branchOf(dir)
  run(dir, 'switch', '-qc', name)
  write(dir, `${name}.txt`, `${name}\n`)
  run(dir, 'add', '.')
  run(dir, 'commit', '-qm', name)
  run(dir, 'switch', '-q', back)
}

/** The usual situation: `held` in the primary checkout, `waiting` in slot 1. */
function twoLanes(dir: string): string {
  branch(dir, 'held')
  branch(dir, 'waiting')
  run(dir, 'switch', '-q', 'held')
  const slot = join(dir, '.worktrees/wt-1')
  mkdirSync(join(dir, '.worktrees'), { recursive: true })
  run(dir, 'worktree', 'add', '-q', slot, 'waiting')
  return slot
}

/** Everything a rollback must put back exactly. */
function state(dir: string, slot: string): string {
  const side = (path: string) => [branchOf(path), run(path, 'rev-parse', 'HEAD').trim(), status(path)].join('|')
  return [side(dir), side(slot)].join('\n')
}

beforeEach(() => {
  repo = makeRepo(join(workspace(), 'api'))
  ignoreWorktrees(repo)
})

describe('swap', { timeout: 30_000 }, () => {
  it('trades branches between folders, carrying uncommitted work, tracked and untracked, and keeping staging', async () => {
    const slot = twoLanes(repo)
    write(repo, 'held.txt', 'held edited\n')
    write(repo, 'held-new.txt', 'new in held\n')
    write(slot, 'waiting.txt', 'waiting edited\n')
    run(slot, 'add', 'waiting.txt')
    write(slot, 'waiting-new.txt', 'new in waiting\n')

    const result = await swap(repo, 'waiting')
    await commit(repo)

    expect(result).toMatchObject({ movedOut: 'held', slotPath: slot })
    expect(branchOf(repo)).toBe('waiting')
    expect(branchOf(slot)).toBe('held')
    expect(read(repo, 'waiting.txt')).toBe('waiting edited\n')
    expect(read(repo, 'waiting-new.txt')).toBe('new in waiting\n')
    expect(status(repo)).toContain('M  waiting.txt')
    expect(read(slot, 'held.txt')).toBe('held edited\n')
    expect(read(slot, 'held-new.txt')).toBe('new in held\n')
    expect(stashes(repo)).toBe('')
    expect(refs(repo)).toBe('')
    expect(await readJournal(repo)).toBeUndefined()
  })

  it('keeps the slot path and its ignored files, such as installed dependencies', async () => {
    write(repo, '.gitignore', 'node_modules/\n')
    run(repo, 'add', '.')
    run(repo, 'commit', '-qm', 'ignore')
    const slot = twoLanes(repo)
    mkdirSync(join(slot, 'node_modules'))
    write(join(slot, 'node_modules'), 'dep.js', 'installed\n')
    const inode = statSync(join(slot, 'node_modules/dep.js')).ino
    await swap(repo, 'waiting')
    await commit(repo)
    expect(statSync(join(slot, 'node_modules/dep.js')).ino).toBe(inode)
    expect(existsSync(slot)).toBe(true)
  })

  it('reports setup only where a lockfile changed', async () => {
    const slot = twoLanes(repo)
    let result = await swap(repo, 'waiting')
    await commit(repo)
    expect(result.setupNeeded).toEqual([])
    run(slot, 'switch', '-q', 'held')
    write(slot, 'pnpm-lock.yaml', 'v2\n')
    run(slot, 'add', '.')
    run(slot, 'commit', '-qm', 'deps')
    result = await swap(repo, 'held')
    await commit(repo)
    expect(result.setupNeeded).toEqual([repo, slot])
  })

  it('moves a cold lane in and makes a slot for the outgoing lane', async () => {
    branch(repo, 'held')
    branch(repo, 'cold')
    run(repo, 'switch', '-q', 'held')
    write(repo, 'held.txt', 'edited\n')
    const result = await swap(repo, 'cold')
    await commit(repo)
    expect(branchOf(repo)).toBe('cold')
    expect(result.slotPath).toBe(join(repo, '.worktrees/wt-1'))
    expect(read(result.slotPath ?? '', 'held.txt')).toBe('edited\n')
  })

  it('needs no slot when the primary checkout is clean on the base branch', async () => {
    branch(repo, 'cold')
    const result = await swap(repo, 'cold')
    await commit(repo)
    expect(result).toEqual({ setupNeeded: [] })
    expect(branchOf(repo)).toBe('cold')
    expect((await worktrees(repo)).length).toBe(1)
  })

  it('does nothing when the lane is already in the primary checkout', async () => {
    run(repo, 'switch', '-qc', 'here')
    expect(await swap(repo, 'here')).toEqual({ noop: true, setupNeeded: [] })
  })

  it('makes uncommitted work on the base branch a lane, when asked to', async () => {
    branch(repo, 'waiting')
    write(repo, 'README.md', 'started here\n')
    expect((await preflight(repo, 'waiting')).kind).toBe('ask')
    const result = await swap(repo, 'waiting', { makeLane: 'started-on-main' })
    await commit(repo)
    expect(branchOf(repo)).toBe('waiting')
    expect(result.movedOut).toBe('started-on-main')
    expect(read(result.slotPath ?? '', 'README.md')).toBe('started here\n')
    expect(run(repo, 'show', 'main:README.md')).toBe('# repo\n')
  })
})

describe('preflight', { timeout: 30_000 }, () => {
  const expectUnchanged = async (lane: string, kind: 'ask' | 'stop') => {
    const before = run(repo, 'worktree', 'list', '--porcelain') + status(repo)
    const verdict = await preflight(repo, lane)
    expect(verdict.kind).toBe(kind)
    expect(run(repo, 'worktree', 'list', '--porcelain') + status(repo)).toBe(before)
    await expect(swap(repo, lane)).rejects.toThrow()
    expect(run(repo, 'worktree', 'list', '--porcelain') + status(repo)).toBe(before)
    return verdict
  }

  it('asks when a worktree it did not create holds the branch', async () => {
    branch(repo, 'waiting')
    run(repo, 'worktree', 'add', '-q', join(repo, '..', 'mine'), 'waiting')
    await expectUnchanged('waiting', 'ask')
  })

  it('asks about ignored files the lane tracks, and names them', async () => {
    branch(repo, 'waiting')
    run(repo, 'switch', '-qc', 'tracks-it')
    write(repo, 'build.out', 'tracked here\n')
    run(repo, 'add', '.')
    run(repo, 'commit', '-qm', 'tracked')
    run(repo, 'switch', '-q', 'main')
    writeFileSync(join(repo, '.git/info/exclude'), '.worktrees/\nbuild.out\n')
    write(repo, 'build.out', 'my local build\n')
    const verdict = await expectUnchanged('tracks-it', 'ask')
    expect(verdict).toMatchObject({ files: ['build.out'] })
    expect(read(repo, 'build.out')).toBe('my local build\n')
  })

  it('names an ignored collision without reading a large ignore set', async () => {
    branch(repo, 'waiting')
    run(repo, 'switch', '-qc', 'tracks-it')
    write(repo, 'build.out', 'tracked here\n')
    run(repo, 'add', '.')
    run(repo, 'commit', '-qm', 'tracked')
    run(repo, 'switch', '-q', 'main')
    writeFileSync(join(repo, '.git/info/exclude'), '.worktrees/\nbuild.out\nignored/\n')
    write(repo, 'build.out', 'my local build\n')
    const dir = join(repo, 'ignored')
    mkdirSync(dir)
    const prefix = 'n'.repeat(200)
    for (let i = 0; i < 100_000; i++) closeSync(openSync(join(dir, prefix + i), 'w'))
    const verdict = await preflight(repo, 'tracks-it')
    expect(verdict).toMatchObject({ kind: 'ask', files: ['build.out'] })
  }, 180_000)

  it('asks when the lane renames a file onto an ignored path', async () => {
    write(repo, 'old.txt', 'was\n')
    run(repo, 'add', '.')
    run(repo, 'commit', '-qm', 'old')
    run(repo, 'switch', '-qc', 'renamed')
    run(repo, 'mv', 'old.txt', 'build.out')
    run(repo, 'commit', '-qm', 'rename')
    run(repo, 'switch', '-q', 'main')
    writeFileSync(join(repo, '.git/info/exclude'), '.worktrees/\nbuild.out\n')
    write(repo, 'build.out', 'my local build\n')
    const verdict = await preflight(repo, 'renamed')
    expect(verdict).toMatchObject({ kind: 'ask', files: ['build.out'] })
  })

  it('asks about an ignored file whose name contains brackets or spaces', async () => {
    run(repo, 'switch', '-qc', 'odd-name')
    mkdirSync(join(repo, 'build'))
    write(join(repo, 'build'), 'a[b].js', 'tracked\n')
    write(repo, 'my build.out', 'tracked\n')
    run(repo, 'add', '.')
    run(repo, 'commit', '-qm', 'odd')
    run(repo, 'switch', '-q', 'main')
    writeFileSync(join(repo, '.git/info/exclude'), '.worktrees/\nbuild/\nmy build.out\n')
    mkdirSync(join(repo, 'build'))
    write(join(repo, 'build'), 'a[b].js', 'local\n')
    write(repo, 'my build.out', 'local\n')
    const verdict = await preflight(repo, 'odd-name')
    expect(verdict).toMatchObject({ kind: 'ask', files: ['build/a[b].js', 'my build.out'] })
  })

  it('stops during a merge', async () => {
    branch(repo, 'waiting')
    for (const [name, text] of [['one', 'a\n'], ['two', 'b\n']] as const) {
      run(repo, 'switch', '-qc', name, 'main')
      write(repo, 'clash.txt', text)
      run(repo, 'add', '.')
      run(repo, 'commit', '-qm', name)
    }
    expect(() => execFileSync('git', ['merge', 'one'], { cwd: repo, stdio: 'ignore' })).toThrow()
    const verdict = await expectUnchanged('waiting', 'stop')
    expect(verdict).toMatchObject({ reason: expect.stringContaining('merge') })
  })

  it('stops on a detached HEAD', async () => {
    branch(repo, 'waiting')
    run(repo, 'switch', '-q', '--detach')
    await expectUnchanged('waiting', 'stop')
  })

  it('stops on a locked worktree', async () => {
    const slot = twoLanes(repo)
    run(repo, 'worktree', 'lock', slot)
    await expectUnchanged('waiting', 'stop')
  })

  it('stops on submodule changes', async () => {
    const lib = makeRepo(join(repo, '..', 'lib'))
    branch(repo, 'waiting')
    run(repo, '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', lib, 'lib')
    run(repo, 'commit', '-qm', 'submodule')
    write(lib, 'more.txt', 'more\n')
    run(lib, 'add', '.')
    run(lib, 'commit', '-qm', 'more')
    run(join(repo, 'lib'), '-c', 'protocol.file.allow=always', 'pull', '-q', lib, 'main')
    await expectUnchanged('waiting', 'stop')
  })

  it('asks when every slot is taken', async () => {
    branch(repo, 'held')
    branch(repo, 'cold')
    for (const name of ['a', 'b']) await newLane(repo, name, { maxSlots: 2 })
    run(repo, 'switch', '-q', 'held')
    expect(await preflight(repo, 'cold', { maxSlots: 2 })).toMatchObject({ kind: 'ask' })
    await expect(newLane(repo, 'c', { maxSlots: 2 })).rejects.toThrow('slots')
  })
})

describe('failures', { timeout: 60_000 }, () => {
  const dirtySides = (slot: string) => {
    write(repo, 'held.txt', 'held edited\n')
    write(repo, 'held-new.txt', 'new in held\n')
    write(slot, 'waiting.txt', 'waiting edited\n')
    write(slot, 'waiting-new.txt', 'new in waiting\n')
  }
  const expectIntact = (slot: string, before: string) => {
    expect(state(repo, slot)).toBe(before)
    expect(read(repo, 'held.txt')).toBe('held edited\n')
    expect(read(repo, 'held-new.txt')).toBe('new in held\n')
    expect(read(slot, 'waiting.txt')).toBe('waiting edited\n')
    expect(read(slot, 'waiting-new.txt')).toBe('new in waiting\n')
    expect(stashes(repo)).not.toContain('canopy:held')
    expect(refs(repo)).toBe('')
  }

  for (const step of ALL_STEPS) {
    it(`restores both sides when ${step} fails`, async () => {
      const slot = twoLanes(repo)
      dirtySides(slot)
      const before = state(repo, slot)
      await expect(swap(repo, 'waiting', { failBefore: step })).rejects.toThrow('Injected')
      expectIntact(slot, before)
      expect(await readJournal(repo)).toBeUndefined()
    })

    it(`recovers on the next start after a crash at ${step}`, async () => {
      const slot = twoLanes(repo)
      dirtySides(slot)
      const before = state(repo, slot)
      await expect(swap(repo, 'waiting', { failBefore: step, crash: true })).rejects.toThrow()
      expect(await readJournal(repo)).toBeDefined()
      expect(await rollback(repo)).toBe(true)
      expectIntact(slot, before)
    })
  }

  it('removes a slot it created when the switch fails', async () => {
    branch(repo, 'held')
    branch(repo, 'cold')
    run(repo, 'switch', '-q', 'held')
    write(repo, 'held.txt', 'edited\n')
    await expect(swap(repo, 'cold', { failBefore: 'restore-slot' })).rejects.toThrow('Injected')
    expect(branchOf(repo)).toBe('held')
    expect(read(repo, 'held.txt')).toBe('edited\n')
    expect((await worktrees(repo)).length).toBe(1)
  })

  it('undoes making a lane when the switch fails', async () => {
    branch(repo, 'waiting')
    write(repo, 'README.md', 'started here\n')
    await expect(swap(repo, 'waiting', { makeLane: 'started', failBefore: 'verify' })).rejects.toThrow('Injected')
    expect(branchOf(repo)).toBe('main')
    expect(read(repo, 'README.md')).toBe('started here\n')
    expect(run(repo, 'branch', '--list', 'started').trim()).toBe('')
  })

  it('undoes making a lane when the failure comes before any snapshot', async () => {
    branch(repo, 'waiting')
    write(repo, 'README.md', 'started here\n')
    await expect(swap(repo, 'waiting', { makeLane: 'started', failBefore: 'snapshot-primary' })).rejects.toThrow('Injected')
    expect(branchOf(repo)).toBe('main')
    expect(read(repo, 'README.md')).toBe('started here\n')
    expect(stashes(repo)).toBe('')
  })

  it('finds a snapshot when a crash came before the journal was saved', async () => {
    const slot = twoLanes(repo)
    dirtySides(slot)
    const before = state(repo, slot)
    await expect(swap(repo, 'waiting', { failBefore: 'snapshot-slot', crash: true })).rejects.toThrow()
    const path = join(repo, '.git/canopy-switch.json')
    const journal = JSON.parse(readFileSync(path, 'utf8'))
    delete journal.primary.stash
    delete journal.primary.ref
    writeFileSync(path, JSON.stringify(journal))
    await rollback(repo)
    expectIntact(slot, before)
  })

  it('survives the user clearing the stash list mid-switch', async () => {
    const slot = twoLanes(repo)
    dirtySides(slot)
    const before = state(repo, slot)
    await expect(swap(repo, 'waiting', { failBefore: 'restore-primary', crash: true })).rejects.toThrow()
    run(repo, 'stash', 'clear')
    await rollback(repo)
    expectIntact(slot, before)
  })

  it('does not lose work when a user edit appears in the slot before recovery', async () => {
    const slot = twoLanes(repo)
    dirtySides(slot)
    await expect(swap(repo, 'waiting', { failBefore: 'restore-primary', crash: true })).rejects.toThrow()
    write(slot, 'edited-during-crash.txt', 'do not lose me\n')
    await rollback(repo)
    expect(stashes(repo)).toContain('rollback-leftovers')
    expect(read(slot, 'waiting.txt')).toBe('waiting edited\n')
  })
})

describe('multiple repos', { timeout: 30_000 }, () => {
  let other: string
  let slotA: string
  let slotB: string

  beforeEach(() => {
    other = makeRepo(join(repo, '..', 'ui'))
    ignoreWorktrees(other)
    slotA = twoLanes(repo)
    slotB = twoLanes(other)
    write(repo, 'held.txt', 'api edited\n')
    write(other, 'held.txt', 'ui edited\n')
  })

  it('moves every repo', async () => {
    await swapAll([repo, other], 'waiting')
    for (const dir of [repo, other]) {
      expect(branchOf(dir)).toBe('waiting')
      expect(await readJournal(dir)).toBeUndefined()
    }
    expect(read(slotA, 'held.txt')).toBe('api edited\n')
    expect(read(slotB, 'held.txt')).toBe('ui edited\n')
  })

  it('moves no repo when preflight fails in one', async () => {
    run(other, 'worktree', 'lock', slotB)
    await expect(swapAll([repo, other], 'waiting')).rejects.toThrow('locked')
    expect(branchOf(repo)).toBe('held')
    expect(branchOf(other)).toBe('held')
  })

  it('handles primary checkouts holding different lanes', async () => {
    run(other, 'worktree', 'remove', '--force', slotB)
    branch(other, 'ui-lane')
    run(other, 'switch', '-q', 'ui-lane')
    write(other, 'ui-lane.txt', 'ui edited\n')
    run(other, 'worktree', 'add', '-q', join(other, '.worktrees/wt-1'), 'waiting')
    await swapAll([repo, other], 'waiting')
    expect(branchOf(repo)).toBe('waiting')
    expect(branchOf(other)).toBe('waiting')
    expect(branchOf(slotA)).toBe('held')
    expect(branchOf(join(other, '.worktrees/wt-1'))).toBe('ui-lane')
    expect(read(join(other, '.worktrees/wt-1'), 'ui-lane.txt')).toBe('ui edited\n')
  })

  it('undoes finished repos when a later repo fails', async () => {
    const before = [state(repo, slotA), state(other, slotB)]
    await expect(swapAll([repo, other], 'waiting', { failRepo: other, failBefore: 'verify' })).rejects.toThrow('Injected')
    expect([state(repo, slotA), state(other, slotB)]).toEqual(before)
    expect(read(repo, 'held.txt')).toBe('api edited\n')
    expect(read(other, 'held.txt')).toBe('ui edited\n')
  })
})

describe('other moves', { timeout: 30_000 }, () => {
  it('takes a lane out of the primary checkout with its work, and puts the base branch back', async () => {
    branch(repo, 'held')
    run(repo, 'switch', '-q', 'held')
    write(repo, 'held.txt', 'edited\n')
    const { slotPath } = await moveToWorktree(repo, 'held')
    expect(branchOf(repo)).toBe('main')
    expect(read(slotPath ?? '', 'held.txt')).toBe('edited\n')
    expect(stashes(repo)).toBe('')
  })

  it('joins a repo in a slot, or in the primary checkout when it is free', async () => {
    expect(await joinRepo(repo, 'in-slot', { worktrees: true })).toMatchObject({ path: join(repo, '.worktrees/wt-1'), setupNeeded: true })
    expect(await joinRepo(repo, 'in-slot', { worktrees: true })).toMatchObject({ setupNeeded: false })
    expect(await joinRepo(repo, 'here', { worktrees: false })).toMatchObject({ path: repo })
    expect(branchOf(repo)).toBe('here')
    await expect(joinRepo(repo, 'other', { worktrees: false })).rejects.toThrow('busy')
  })

  it('moves lane-named worktrees into slots, with their work, and keeps them managed', async () => {
    run(repo, 'branch', 'feat/old')
    mkdirSync(join(repo, '.worktrees'))
    const old = join(repo, '.worktrees/feat--old')
    run(repo, 'worktree', 'add', '-q', old, 'feat/old')
    write(old, 'wip.txt', 'wip\n')
    expect(await migrateToSlots(repo)).toEqual([join(repo, '.worktrees/wt-1')])
    expect(existsSync(old)).toBe(false)
    expect(read(join(repo, '.worktrees/wt-1'), 'wip.txt')).toBe('wip\n')
    expect(await migrateToSlots(repo)).toEqual([])
    expect((await preflight(repo, 'feat/old')).kind).toBe('ok')
  })

  it('asks with a question the caller can tell from a failure', async () => {
    branch(repo, 'waiting')
    write(repo, 'README.md', 'started here\n')
    await expect(swap(repo, 'waiting')).rejects.toBeInstanceOf(SwitchQuestion)
  })
})

describe('slots', { timeout: 30_000 }, () => {
  it('reads occupancy from Git, including slots made by hand and other worktrees', async () => {
    branch(repo, 'by-hand')
    branch(repo, 'elsewhere')
    mkdirSync(join(repo, '.worktrees'))
    run(repo, 'worktree', 'add', '-q', join(repo, '.worktrees/wt-2'), 'by-hand')
    run(repo, 'worktree', 'add', '-q', join(repo, '..', 'elsewhere'), 'elsewhere')
    const all = await worktrees(repo)
    expect(all.find((tree) => tree.branch === 'by-hand')?.slot).toBe(2)
    expect(all.find((tree) => tree.branch === 'elsewhere')?.slot).toBeUndefined()
    expect((await newLane(repo, 'fresh')).path).toBe(join(repo, '.worktrees/wt-1'))
  })

  it('reuses a parked slot for a new lane, keeping its ignored files', async () => {
    writeFileSync(join(repo, '.git/info/exclude'), '.worktrees/\nnode_modules/\n')
    const { path } = await newLane(repo, 'first')
    mkdirSync(join(path, 'node_modules'))
    write(join(path, 'node_modules'), 'dep.js', 'installed\n')
    await park(repo, 'first')
    expect(run(repo, 'branch', '--list', 'first').trim()).not.toBe('')
    const next = await newLane(repo, 'second')
    expect(next).toEqual({ path, reused: true, setupNeeded: false })
    expect(read(join(path, 'node_modules'), 'dep.js')).toBe('installed\n')
    expect(branchOf(path)).toBe('second')
  })

  it('refuses to park a lane with uncommitted work', async () => {
    const { path } = await newLane(repo, 'first')
    write(path, 'wip.txt', 'wip\n')
    await expect(park(repo, 'first')).rejects.toThrow('uncommitted')
  })

  it('fills a parked slot when an outgoing lane needs one', async () => {
    branch(repo, 'held')
    branch(repo, 'cold')
    const { path } = await newLane(repo, 'first')
    await park(repo, 'first')
    run(repo, 'switch', '-q', 'held')
    const result = await swap(repo, 'cold')
    await commit(repo)
    expect(result.slotPath).toBe(path)
    expect(branchOf(path)).toBe('held')
  })

  it('keeps working through repeated switches', async () => {
    const slot = twoLanes(repo)
    write(repo, 'held.txt', 'held v1\n')
    write(slot, 'waiting.txt', 'waiting v1\n')
    for (const lane of ['waiting', 'held', 'waiting', 'held']) {
      await swap(repo, lane)
      await commit(repo)
      expect(branchOf(repo)).toBe(lane)
    }
    expect(read(repo, 'held.txt')).toBe('held v1\n')
    expect(read(slot, 'waiting.txt')).toBe('waiting v1\n')
    expect(await git(repo, ['stash', 'list'])).toBe('')
  })
})
