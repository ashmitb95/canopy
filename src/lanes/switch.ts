import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { git } from './git'
import type { RepoState } from './state'

/** A switch step that cannot complete cleanly; the message says what was left where. */
export class SwitchError extends Error {}

export function worktreePath(repo: string, lane: string): string {
  return join(repo, '.worktrees', lane.replaceAll('/', '--'))
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

async function branchExists(repo: string, branch: string): Promise<boolean> {
  return git(repo, ['rev-parse', '--verify', '--quiet', `refs/heads/${branch}`]).then(
    () => true,
    () => false
  )
}

async function isDirty(path: string): Promise<boolean> {
  return (await git(path, ['status', '--porcelain'])).trim() !== ''
}

/** Stashes uncommitted work, untracked files included, under a unique message; undefined when clean. */
async function stash(path: string, lane: string): Promise<string | undefined> {
  if (!(await isDirty(path))) return undefined
  const message = `agentdeck:${lane}:${Date.now()}`
  await git(path, ['stash', 'push', '--include-untracked', '-m', message])
  return message
}

/** Re-applies a stash made by `stash`. On conflict the stash is kept and the switch stops. */
async function unstash(path: string, message: string | undefined): Promise<void> {
  if (!message) return
  const list = await git(path, ['stash', 'list', '--format=%gd %gs'])
  const ref = list
    .split('\n')
    .find((line) => line.endsWith(message))
    ?.split(' ')[0]
  if (!ref) throw new SwitchError(`The stash “${message}” is missing.`)
  try {
    await git(path, ['stash', 'pop', ref])
  } catch {
    throw new SwitchError(
      `Uncommitted changes did not re-apply cleanly in ${path}. They are kept in ${ref} (“${message}”): resolve the conflict, then drop that stash.`
    )
  }
}

export type MoveResult = { movedOut?: string; worktree?: string }

/** Brings `lane` into the repo's main checkout. The lane holding main moves to a worktree; uncommitted work travels with each lane. */
export async function moveIntoMain(repo: RepoState, lane: string): Promise<MoveResult> {
  const main = repo.checkouts.find((checkout) => checkout.main)
  if (!main) throw new SwitchError(`${repo.name} has no main checkout.`)
  if (main.branch === lane) return {}
  await excludeWorktrees(repo.path)
  const holder = main.branch && main.branch !== repo.base ? main.branch : undefined
  if (!holder && (await isDirty(main.path))) {
    throw new SwitchError(
      `${repo.name} has uncommitted changes on ${main.branch ?? 'a detached HEAD'}. Commit or stash them, then move ${lane} in.`
    )
  }
  const heldWork = holder ? await stash(main.path, holder) : undefined
  const own = repo.checkouts.find((checkout) => !checkout.main && checkout.branch === lane)
  let laneWork: string | undefined
  if (own) {
    laneWork = await stash(own.path, lane)
    // A branch cannot be checked out twice; its worktree goes, its work came along in the stash.
    await git(repo.path, ['worktree', 'remove', own.path])
  }
  if (await branchExists(repo.path, lane)) await git(main.path, ['checkout', lane])
  else await git(main.path, ['checkout', '-b', lane, repo.base ?? 'HEAD'])
  await unstash(main.path, laneWork)
  if (!holder) return {}
  const worktree = worktreePath(repo.path, holder)
  await git(repo.path, ['worktree', 'add', worktree, holder])
  await unstash(worktree, heldWork)
  return { movedOut: holder, worktree }
}

/** Moves `lane` out of the main checkout into its worktree (main goes back to base); for a parked lane, makes the worktree. */
export async function moveToWorktree(repo: RepoState, lane: string): Promise<string> {
  const main = repo.checkouts.find((checkout) => checkout.main)
  if (main?.branch !== lane) {
    const existing = repo.checkouts.find((checkout) => checkout.branch === lane)
    if (existing) return existing.path
    if (!(await branchExists(repo.path, lane))) throw new SwitchError(`${repo.name} has no branch ${lane}.`)
    await excludeWorktrees(repo.path)
    const worktree = worktreePath(repo.path, lane)
    await git(repo.path, ['worktree', 'add', worktree, lane])
    return worktree
  }
  if (!repo.base) throw new SwitchError(`${repo.name} has no base branch to put back in main.`)
  await excludeWorktrees(repo.path)
  const work = await stash(main.path, lane)
  await git(main.path, ['checkout', repo.base])
  const worktree = worktreePath(repo.path, lane)
  await git(repo.path, ['worktree', 'add', worktree, lane])
  await unstash(worktree, work)
  return worktree
}

/** Starts `lane` in a repo: in a worktree, or (worktrees off) in the main checkout when that is clean and on base. */
export async function joinRepo(repo: RepoState, lane: string, worktrees: boolean): Promise<string> {
  const existing = repo.checkouts.find((checkout) => checkout.branch === lane)
  if (existing) return existing.path
  const exists = await branchExists(repo.path, lane)
  if (worktrees) {
    await excludeWorktrees(repo.path)
    const worktree = worktreePath(repo.path, lane)
    await git(repo.path, exists ? ['worktree', 'add', worktree, lane] : ['worktree', 'add', '-b', lane, worktree, repo.base ?? 'HEAD'])
    return worktree
  }
  const main = repo.checkouts.find((checkout) => checkout.main)
  if (!main) throw new SwitchError(`${repo.name} has no main checkout.`)
  if (main.branch !== repo.base || (await isDirty(main.path))) {
    throw new SwitchError(
      `${repo.name}'s main checkout is busy (${main.branch ?? 'detached HEAD'}). Move ${lane} into main from AgentDeck, or turn worktrees on for this lane.`
    )
  }
  await git(main.path, exists ? ['checkout', lane] : ['checkout', '-b', lane])
  return main.path
}
