import { existsSync } from 'node:fs'
import { basename, relative } from 'node:path'
import { git } from './git'

/** One checkout of a repo: the primary checkout or a linked worktree. `branch` is absent on a detached HEAD. */
export type Checkout = { path: string; primary: boolean; head?: string; branch?: string; dirty: number }

export type RepoState = {
  path: string
  /** Path relative to the workspace root, or the folder name when the root is the repo. */
  name: string
  /** The branch nobody "works on": origin's default, else main, master, develop, or trunk. */
  base?: string
  checkouts: Checkout[]
}

/** Parses `git worktree list --porcelain`; the first entry is the primary checkout. */
export function parseWorktrees(text: string): Omit<Checkout, 'dirty'>[] {
  return text
    .split('\n\n')
    .map((block) => block.trim())
    .filter(Boolean)
    .flatMap((block, index) => {
      const lines = block.split('\n')
      const path = lines.find((line) => line.startsWith('worktree '))?.slice('worktree '.length)
      if (!path || lines.includes('bare')) return []
      const branch = lines.find((line) => line.startsWith('branch refs/heads/'))?.slice('branch refs/heads/'.length)
      const head = lines.find((line) => line.startsWith('HEAD '))?.slice('HEAD '.length)
      return [{ path, primary: index === 0, ...(head ? { head } : {}), ...(branch ? { branch } : {}) }]
    })
}

async function baseBranch(path: string): Promise<string | undefined> {
  const remote = (await git(path, ['symbolic-ref', '--quiet', '--short', 'refs/remotes/origin/HEAD']).catch(() => '')).trim()
  if (remote) return remote.replace(/^origin\//, '')
  for (const name of ['main', 'master', 'develop', 'trunk']) {
    const exists = await git(path, ['rev-parse', '--verify', '--quiet', `refs/heads/${name}`]).then(
      () => true,
      () => false
    )
    if (exists) return name
  }
  return undefined
}

async function dirtyFiles(path: string): Promise<number> {
  const status = await git(path, ['status', '--porcelain']).catch(() => '')
  // The worktrees folder sits inside the primary checkout; it is not uncommitted work.
  return status.split('\n').filter((line) => line && line !== '?? .worktrees/').length
}

export async function readRepo(root: string, path: string): Promise<RepoState> {
  const [list, base] = await Promise.all([git(path, ['worktree', 'list', '--porcelain']), baseBranch(path)])
  const checkouts = await Promise.all(
    parseWorktrees(list)
      // A worktree whose folder was deleted by hand is listed until pruned; it has nothing to show.
      .filter((checkout) => existsSync(checkout.path))
      .map(async (checkout) => ({ ...checkout, dirty: await dirtyFiles(checkout.path) }))
  )
  return { path, name: relative(root, path) || basename(path), ...(base ? { base } : {}), checkouts }
}
