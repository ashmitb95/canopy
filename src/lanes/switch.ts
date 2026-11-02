// Moves lanes between the primary checkout and generically named worktree slots, as transactions:
// nothing changes until a move can finish, and a failed or interrupted move can be undone.
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, isAbsolute, join, sep } from 'node:path'
import { git } from './git'

/** A move that cannot go ahead or finish; the message says why, and nothing was left half done. */
export class SwitchError extends Error {}

/** A move that needs the user to decide first. Nothing has changed. */
export class SwitchQuestion extends SwitchError {
  constructor(
    message: string,
    readonly files: string[] = []
  ) {
    super(message)
  }
}

/** `.worktrees/` stays out of the repo's status and stashes, without touching a committed .gitignore. */
export async function excludeWorktrees(repo: string): Promise<void> {
  const common = (await git(repo, ['rev-parse', '--path-format=absolute', '--git-common-dir'])).trim()
  const file = join(common, 'info', 'exclude')
  const current = existsSync(file) ? readFileSync(file, 'utf8') : ''
  if (current.split('\n').includes('.worktrees/')) return
  mkdirSync(dirname(file), { recursive: true })
  appendFileSync(file, `${current && !current.endsWith('\n') ? '\n' : ''}.worktrees/\n`)
}

const attempt = async (cwd: string, args: string[]) => git(cwd, args).then(() => true, () => false)

/** `managed` worktrees live in `.worktrees/`; a slot is a managed one named `wt-<n>`. */
export type Worktree = { path: string; branch?: string; primary: boolean; locked: boolean; managed: boolean; slot?: number }

/** Occupancy comes only from Git: nothing about slots is stored. */
export async function worktrees(repo: string): Promise<Worktree[]> {
  const blocks = (await git(repo, ['worktree', 'list', '--porcelain'])).trim().split('\n\n')
  return blocks.map((block, index) => {
    const lines = block.split('\n')
    const path = lines[0].slice('worktree '.length)
    const branch = lines.find((line) => line.startsWith('branch refs/heads/'))?.slice('branch refs/heads/'.length)
    const managed = path.startsWith(join(repo, '.worktrees') + sep)
    const number = managed ? /[/\\]wt-(\d+)$/.exec(path)?.[1] : undefined
    return { path, primary: index === 0, managed, locked: lines.some((line) => line.startsWith('locked')), ...(branch ? { branch } : {}), ...(number ? { slot: Number(number) } : {}) }
  })
}

// The slots folder sits inside the primary checkout and is not uncommitted work, even before it is excluded.
const dirty = async (path: string) => (await git(path, ['status', '--porcelain'])).split('\n').some((line) => line.trim() !== '' && line !== '?? .worktrees/')

async function inProgress(path: string): Promise<string | undefined> {
  const markers: [string, string][] = [['MERGE_HEAD', 'a merge'], ['rebase-merge', 'a rebase'], ['rebase-apply', 'a rebase'], ['CHERRY_PICK_HEAD', 'a cherry-pick'], ['REVERT_HEAD', 'a revert'], ['BISECT_LOG', 'a bisect']]
  for (const [name, label] of markers) {
    const raw = (await git(path, ['rev-parse', '--git-path', name])).trim()
    if (existsSync(isAbsolute(raw) ? raw : join(path, raw))) return label
  }
  return undefined
}

async function submoduleChanges(path: string): Promise<boolean> {
  if (!existsSync(join(path, '.gitmodules'))) return false
  return (await git(path, ['submodule', 'status'])).split('\n').some((line) => line.startsWith('+') || line.startsWith('U'))
}

/** Ignored files a checkout would refuse to overwrite: tracked on `branch` but ignored here. Stashes carry everything else. */
async function collisions(path: string, branch: string): Promise<string[]> {
  const ignored = (await git(path, ['ls-files', '--others', '--ignored', '--exclude-standard'])).split('\n').filter(Boolean)
  if (ignored.length === 0) return []
  const tracked = new Set((await git(path, ['ls-tree', '-r', '--name-only', branch])).split('\n'))
  return ignored.filter((file) => tracked.has(file))
}

export type Verdict = { kind: 'ok'; noop?: boolean } | { kind: 'ask'; reason: string; files?: string[] } | { kind: 'stop'; reason: string }

export type SwapOptions = {
  base?: string
  maxSlots?: number
  /** Answers "make it a lane" when the primary checkout has uncommitted work on the base branch. */
  makeLane?: string
  /** Answers yes to taking a branch from a worktree AgentDeck did not create. */
  takeForeign?: boolean
  /** Fails the move just before this step, for tests. */
  failBefore?: Step
  /** Dies at `failBefore` without rolling back, as a crash would. */
  crash?: boolean
}

/** Changes nothing. Every repo must pass before any repo moves. */
export async function preflight(repo: string, lane: string, options: SwapOptions = {}): Promise<Verdict> {
  const base = options.base ?? 'main'
  const all = await worktrees(repo)
  const primary = all[0]
  if (primary.branch === lane) return { kind: 'ok', noop: true }
  if (!primary.branch) return { kind: 'stop', reason: 'The primary checkout is on a detached HEAD.' }
  if (!(await attempt(repo, ['rev-parse', '--verify', '--quiet', `refs/heads/${lane}`]))) return { kind: 'stop', reason: `There is no branch ${lane}.` }
  const holder = all.find((tree) => tree.branch === lane)
  for (const tree of [primary, ...(holder ? [holder] : [])]) {
    const busy = await inProgress(tree.path)
    if (busy) return { kind: 'stop', reason: `${tree.path} is in the middle of ${busy}.` }
    if (await submoduleChanges(tree.path)) return { kind: 'stop', reason: `${tree.path} has submodule changes.` }
  }
  if (holder?.locked) return { kind: 'stop', reason: `The worktree holding ${lane} is locked.` }
  if (holder && !holder.managed && !options.takeForeign) return { kind: 'ask', reason: `${lane} is checked out in ${holder.path}, which AgentDeck did not create.` }
  if (primary.branch === base && (await dirty(primary.path)) && !options.makeLane) return { kind: 'ask', reason: `The primary checkout has uncommitted work on ${base}. Make it a lane, or stash it.` }
  const files = await collisions(primary.path, lane)
  if (files.length > 0) return { kind: 'ask', reason: `These ignored files would be overwritten by ${lane}.`, files }
  const outgoing = options.makeLane ?? primary.branch
  if (!holder && outgoing !== base) {
    const free = all.find((tree) => tree.slot !== undefined && !tree.branch)
    const used = all.filter((tree) => tree.slot !== undefined).length
    if (!free && used >= (options.maxSlots ?? 4)) return { kind: 'ask', reason: `All ${used} slots are in use. Choose one to free.` }
  }
  return { kind: 'ok' }
}

const STEPS = ['snapshot-primary', 'snapshot-slot', 'detach-slot', 'switch-primary', 'fill-slot', 'restore-primary', 'restore-slot', 'verify'] as const
export type Step = (typeof STEPS)[number]
export const ALL_STEPS: readonly Step[] = STEPS

type Side = { path: string; branch?: string; head: string; stash?: string; ref?: string }
export type Journal = { id: string; lane: string; primary: Side; slot?: Side; createdSlot?: string; makeLane?: { name: string; from: string } }

const commonDir = async (repo: string) => {
  const raw = (await git(repo, ['rev-parse', '--git-common-dir'])).trim()
  return isAbsolute(raw) ? raw : join(repo, raw)
}
const journalPath = async (repo: string) => join(await commonDir(repo), 'agentdeck-switch.json')

async function saveJournal(repo: string, journal: Journal): Promise<void> {
  const path = await journalPath(repo)
  writeFileSync(`${path}.tmp`, JSON.stringify(journal))
  renameSync(`${path}.tmp`, path)
}

export async function readJournal(repo: string): Promise<Journal | undefined> {
  const path = await journalPath(repo)
  return existsSync(path) ? (JSON.parse(readFileSync(path, 'utf8')) as Journal) : undefined
}

/** A named stash of everything uncommitted, pinned so clearing the stash list cannot lose it. */
async function snapshot(side: Side, lane: string, id: string, name: string): Promise<void> {
  if (!(await dirty(side.path))) return
  const before = (await git(side.path, ['rev-parse', '--verify', '--quiet', 'refs/stash']).catch(() => '')).trim()
  await git(side.path, ['stash', 'push', '--include-untracked', '-m', `agentdeck:${lane}:${id}`])
  const hash = (await git(side.path, ['rev-parse', 'refs/stash'])).trim()
  if (hash === before) throw new SwitchError(`Nothing was stashed in ${side.path}.`)
  side.stash = hash
  side.ref = `refs/agentdeck/${id}/${name}`
  await git(side.path, ['update-ref', side.ref, hash])
}

async function dropStash(path: string, hash: string): Promise<void> {
  const list = (await git(path, ['stash', 'list', '--format=%gd %H'])).split('\n')
  const entry = list.find((line) => line.endsWith(` ${hash}`))
  if (entry) await git(path, ['stash', 'drop', entry.split(' ')[0]])
}

async function applyStash(path: string, hash: string): Promise<void> {
  if (!(await attempt(path, ['stash', 'apply', '--index', hash]))) await git(path, ['stash', 'apply', hash])
}

async function forgetSnapshots(repo: string, journal: Journal): Promise<void> {
  for (const side of [journal.primary, journal.slot]) {
    if (!side?.stash || !side.ref) continue
    await dropStash(side.path, side.stash)
    await git(repo, ['update-ref', '-d', side.ref])
  }
  rmSync(await journalPath(repo), { force: true })
}

async function adoptStash(side: Side, lane: string | undefined, id: string, name: string): Promise<void> {
  if (side.stash || !lane) return
  const entry = (await git(side.path, ['stash', 'list', '--format=%H %gs'])).split('\n').find((line) => line.endsWith(`agentdeck:${lane}:${id}`))
  if (!entry) return
  side.stash = entry.split(' ')[0]
  side.ref = `refs/agentdeck/${id}/${name}`
  await git(side.path, ['update-ref', side.ref, side.stash])
}

/** Puts one working folder back: leftovers from a partial attempt are stashed, never discarded. */
async function restoreSide(side: Side, id: string): Promise<void> {
  const current = (await git(side.path, ['branch', '--show-current'])).trim()
  // Not snapshotted and still in place: anything uncommitted is the user's own work, untouched.
  if (!side.stash && current === (side.branch ?? '')) return
  if (await dirty(side.path)) {
    if (!(await attempt(side.path, ['stash', 'push', '--include-untracked', '-m', `agentdeck:rollback-leftovers:${id}`]))) {
      // A failed apply can leave conflicts, which cannot be stashed. Everything in them is in the pinned snapshot.
      await git(side.path, ['reset', '--merge'])
    }
  }
  if (side.branch) await git(side.path, ['switch', side.branch])
  else await git(side.path, ['switch', '--detach', side.head])
  if (side.stash) await applyStash(side.path, side.stash)
}

/** Undoes a transaction from its journal: after a failure, or on the next start after a crash. */
export async function rollback(repo: string): Promise<boolean> {
  const journal = await readJournal(repo)
  if (!journal) return false
  // A crash can land between stashing and saving the journal, so look for snapshots it does not know about.
  await adoptStash(journal.primary, journal.makeLane?.name ?? journal.primary.branch, journal.id, 'primary')
  if (journal.slot) await adoptStash(journal.slot, journal.slot.branch, journal.id, 'slot')
  if (journal.makeLane && !journal.primary.stash) await git(journal.primary.path, ['switch', journal.primary.branch ?? 'main']).catch(() => '')
  // A slot may hold the primary's branch, so free it before the primary takes that branch back.
  const outgoing = journal.makeLane?.name ?? journal.primary.branch
  for (const path of [journal.slot?.path, journal.createdSlot]) {
    if (path && existsSync(path) && (await git(path, ['branch', '--show-current'])).trim() === outgoing) await git(path, ['switch', '--detach'])
  }
  await restoreSide(journal.primary, journal.id)
  if (journal.slot) await restoreSide(journal.slot, journal.id)
  if (journal.createdSlot && existsSync(journal.createdSlot)) await git(repo, ['worktree', 'remove', '--force', journal.createdSlot])
  if (journal.makeLane) await git(journal.primary.path, ['branch', '-D', journal.makeLane.name]).catch(() => '')
  await forgetSnapshots(repo, journal)
  return true
}

export type SwapResult = { noop?: boolean; movedOut?: string; slotPath?: string; setupNeeded: string[] }

const LOCKFILES = ['pnpm-lock.yaml', 'package-lock.json', 'yarn.lock', 'bun.lockb', 'Cargo.lock', 'poetry.lock', 'go.sum']

async function lockfileChanged(path: string, from: string, to: string): Promise<boolean> {
  if (from === to) return false
  return (await git(path, ['diff', '--name-only', from, to, '--', ...LOCKFILES])).trim().length > 0
}

class Crash extends Error {}

/** Moves `lane` into the primary checkout. Keeps the snapshots and journal until `commit`, so a multi-repo switch can still undo. */
export async function swap(repo: string, lane: string, options: SwapOptions = {}): Promise<SwapResult> {
  const verdict = await preflight(repo, lane, options)
  if (verdict.kind === 'ask') throw new SwitchQuestion(verdict.reason, verdict.files)
  if (verdict.kind === 'stop') throw new SwitchError(verdict.reason)
  if (verdict.noop) return { noop: true, setupNeeded: [] }
  await excludeWorktrees(repo)
  const base = options.base ?? 'main'
  const all = await worktrees(repo)
  const primaryTree = all[0]
  const holder = all.find((tree) => tree.branch === lane)
  const id = `${Date.now()}`
  const head = async (path: string) => (await git(path, ['rev-parse', 'HEAD'])).trim()
  const journal: Journal = { id, lane, primary: { path: primaryTree.path, ...(primaryTree.branch ? { branch: primaryTree.branch } : {}), head: await head(primaryTree.path) } }
  if (holder) journal.slot = { path: holder.path, branch: lane, head: await head(holder.path) }
  await saveJournal(repo, journal)
  const step = (name: Step) => {
    if (options.failBefore === name) throw options.crash ? new Crash(name) : new Error(`Injected failure before ${name}`)
  }
  try {
    const setupNeeded: string[] = []
    if (options.makeLane) {
      journal.makeLane = { name: options.makeLane, from: base }
      await saveJournal(repo, journal)
      await git(primaryTree.path, ['switch', '-c', options.makeLane])
    }
    const outgoing = options.makeLane ?? primaryTree.branch ?? base
    step('snapshot-primary')
    await snapshot(journal.primary, outgoing, id, 'primary')
    await saveJournal(repo, journal)
    step('snapshot-slot')
    if (journal.slot) {
      await snapshot(journal.slot, lane, id, 'slot')
      await saveJournal(repo, journal)
    }
    step('detach-slot')
    if (journal.slot) await git(journal.slot.path, ['switch', '--detach'])
    const before = journal.primary.head
    step('switch-primary')
    await git(journal.primary.path, ['switch', lane])
    const after = await head(journal.primary.path)
    if (await lockfileChanged(repo, before, after)) setupNeeded.push(journal.primary.path)
    step('fill-slot')
    let slotPath: string | undefined
    if (outgoing !== base) {
      const fresh = await worktrees(repo)
      const reuse = journal.slot?.path ?? fresh.find((tree) => tree.slot !== undefined && !tree.branch)?.path
      if (reuse) {
        // A freed slot was not part of this lane's journal: record it so a rollback detaches it again.
        if (!journal.slot) {
          journal.slot = { path: reuse, head: await head(reuse) }
          await saveJournal(repo, journal)
        }
        const was = await head(reuse)
        await git(reuse, ['switch', outgoing])
        if (await lockfileChanged(repo, was, await head(reuse))) setupNeeded.push(reuse)
        slotPath = reuse
      } else {
        const numbers = new Set(fresh.flatMap((tree) => tree.slot ?? []))
        let number = 1
        while (numbers.has(number)) number += 1
        slotPath = join(repo, '.worktrees', `wt-${number}`)
        journal.createdSlot = slotPath
        await saveJournal(repo, journal)
        mkdirSync(join(repo, '.worktrees'), { recursive: true })
        await git(repo, ['worktree', 'add', slotPath, outgoing])
        setupNeeded.push(slotPath)
      }
    }
    step('restore-primary')
    if (journal.slot?.stash && journal.slot.branch === lane) await applyStash(journal.primary.path, journal.slot.stash)
    step('restore-slot')
    if (journal.primary.stash && slotPath) await applyStash(slotPath, journal.primary.stash)
    step('verify')
    const now = await worktrees(repo)
    if (now[0].branch !== lane) throw new SwitchError(`The primary checkout is on ${now[0].branch}, not ${lane}.`)
    if (slotPath && now.find((tree) => tree.path === slotPath)?.branch !== outgoing) throw new SwitchError(`The slot does not hold ${outgoing}.`)
    return { ...(outgoing !== base ? { movedOut: outgoing } : {}), ...(slotPath ? { slotPath } : {}), setupNeeded }
  } catch (error) {
    if (!(error instanceof Crash)) await rollback(repo)
    throw error
  }
}

/** Ends a transaction once every repo has moved. */
export async function commit(repo: string): Promise<void> {
  const journal = await readJournal(repo)
  if (journal) await forgetSnapshots(repo, journal)
}

/** All repos move, or none do. */
export async function swapAll(repos: string[], lane: string, options: SwapOptions & { failRepo?: string } = {}): Promise<SwapResult[]> {
  for (const repo of repos) {
    const verdict = await preflight(repo, lane, options)
    if (verdict.kind === 'ask') throw new SwitchQuestion(`${repo}: ${verdict.reason}`, verdict.files)
    if (verdict.kind === 'stop') throw new SwitchError(`${repo}: ${verdict.reason}`)
  }
  const done: string[] = []
  const results: SwapResult[] = []
  try {
    for (const repo of repos) {
      results.push(await swap(repo, lane, repo === options.failRepo ? options : { ...options, failBefore: undefined }))
      done.push(repo)
    }
  } catch (error) {
    for (const repo of done) await rollback(repo)
    throw error
  }
  for (const repo of done) await commit(repo)
  return results
}

/** A new lane in a free slot if there is one, so its dependencies are already installed. */
export async function newLane(repo: string, lane: string, options: { base?: string; maxSlots?: number } = {}): Promise<{ path: string; reused: boolean; setupNeeded: boolean }> {
  const base = options.base ?? 'main'
  await excludeWorktrees(repo)
  const all = await worktrees(repo)
  const held = all.find((tree) => tree.branch === lane)
  if (held) return { path: held.path, reused: false, setupNeeded: false }
  const exists = await attempt(repo, ['rev-parse', '--verify', '--quiet', `refs/heads/${lane}`])
  const free = all.find((tree) => tree.slot !== undefined && !tree.branch)
  if (free) {
    const was = (await git(free.path, ['rev-parse', 'HEAD'])).trim()
    await git(free.path, exists ? ['switch', lane] : ['switch', '-c', lane, base])
    return { path: free.path, reused: true, setupNeeded: await lockfileChanged(repo, was, (await git(free.path, ['rev-parse', 'HEAD'])).trim()) }
  }
  const numbers = new Set(all.flatMap((tree) => tree.slot ?? []))
  if (numbers.size >= (options.maxSlots ?? 4)) throw new SwitchQuestion(`All ${numbers.size} slots are in use. Choose one to free.`)
  let number = 1
  while (numbers.has(number)) number += 1
  const path = join(repo, '.worktrees', `wt-${number}`)
  mkdirSync(join(repo, '.worktrees'), { recursive: true })
  await git(repo, exists ? ['worktree', 'add', path, lane] : ['worktree', 'add', '-b', lane, path, base])
  return { path, reused: false, setupNeeded: true }
}

/** Takes the lane out of the primary checkout: the base branch goes back in, and the lane goes to a slot with its work. */
export async function moveToWorktree(repo: string, lane: string, options: SwapOptions = {}): Promise<SwapResult> {
  const primary = (await worktrees(repo))[0]
  if (primary.branch !== lane) throw new SwitchError(`${lane} is not in the primary checkout.`)
  const result = await swap(repo, options.base ?? 'main', options)
  await commit(repo)
  return result
}

/** Starts a lane in a repo: in a slot, or in the primary checkout when that is clean and on the base branch. */
export async function joinRepo(repo: string, lane: string, options: { base?: string; maxSlots?: number; worktrees: boolean }): Promise<{ path: string; setupNeeded: boolean }> {
  if (options.worktrees) return newLane(repo, lane, options)
  const base = options.base ?? 'main'
  const all = await worktrees(repo)
  const held = all.find((tree) => tree.branch === lane)
  if (held) return { path: held.path, setupNeeded: false }
  const primary = all[0]
  if (primary.branch !== base || (await dirty(primary.path))) {
    throw new SwitchError(`The primary checkout of ${repo} is busy (${primary.branch ?? 'detached HEAD'}). Move ${lane} to it from AgentDeck, or turn worktrees on for this lane.`)
  }
  const exists = await attempt(repo, ['rev-parse', '--verify', '--quiet', `refs/heads/${lane}`])
  await git(primary.path, exists ? ['switch', lane] : ['switch', '-c', lane])
  return { path: primary.path, setupNeeded: false }
}

/** Renames lane-named worktrees to slots, once, when nothing is running in them. */
export async function migrateToSlots(repo: string): Promise<string[]> {
  const all = await worktrees(repo)
  const numbers = new Set(all.flatMap((tree) => tree.slot ?? []))
  const moved: string[] = []
  for (const tree of all.filter((candidate) => candidate.managed && candidate.slot === undefined && !candidate.locked)) {
    let number = 1
    while (numbers.has(number)) number += 1
    numbers.add(number)
    const path = join(repo, '.worktrees', `wt-${number}`)
    await git(repo, ['worktree', 'move', tree.path, path])
    moved.push(path)
  }
  return moved
}

/** A move a crash left unfinished, if any. */
export async function unfinishedMove(repo: string): Promise<Journal | undefined> {
  return readJournal(repo)
}

/** A lane leaves its slot: the branch and work are kept, the folder stays warm for the next lane. */
export async function park(repo: string, lane: string): Promise<void> {
  const tree = (await worktrees(repo)).find((candidate) => candidate.branch === lane)
  if (!tree || tree.slot === undefined) throw new SwitchError(`${lane} is not in a slot.`)
  if (await dirty(tree.path)) throw new SwitchError(`${lane} has uncommitted work in ${tree.path}.`)
  await git(tree.path, ['switch', '--detach'])
}
