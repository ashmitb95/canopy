import { sep } from 'node:path'
import type { RepoState } from './state'

export type LaneRepo = { repo: string; location: 'main' | 'worktree'; path: string; dirty: number; head?: string }

/** A lane is a branch: where it is checked out in each repo is read from Git, never stored. */
export type Lane = { name: string; repos: LaneRepo[] }

function onLane(repo: RepoState, branch: string | undefined): branch is string {
  return branch !== undefined && branch !== repo.base
}

/** Lanes are branches checked out anywhere other than their repo's base, plus lanes chats are linked to. */
export function deriveLanes(repos: RepoState[], linked: Iterable<string> = []): Lane[] {
  const lanes = new Map<string, Lane>()
  const lane = (name: string): Lane => {
    const existing = lanes.get(name)
    if (existing) return existing
    const created: Lane = { name, repos: [] }
    lanes.set(name, created)
    return created
  }
  for (const repo of repos) {
    for (const checkout of repo.checkouts) {
      if (!onLane(repo, checkout.branch)) continue
      lane(checkout.branch).repos.push({
        repo: repo.name,
        location: checkout.main ? 'main' : 'worktree',
        path: checkout.path,
        dirty: checkout.dirty,
        ...(checkout.head ? { head: checkout.head } : {})
      })
    }
  }
  for (const name of linked) lane(name)
  return [...lanes.values()].sort((a, b) => a.name.localeCompare(b.name))
}

/** The lane a file belongs to: the branch of the innermost checkout holding it, unless that is the base or a detached head. */
export function laneForPath(repos: RepoState[], file: string): string | undefined {
  let best: { repo: RepoState; branch?: string; length: number } | undefined
  for (const repo of repos) {
    for (const checkout of repo.checkouts) {
      const inside = file === checkout.path || file.startsWith(checkout.path + sep)
      if (inside && (!best || checkout.path.length > best.length)) {
        best = { repo, branch: checkout.branch, length: checkout.path.length }
      }
    }
  }
  return best && onLane(best.repo, best.branch) ? best.branch : undefined
}

/** The one lane a set of edits landed in, or undefined when they landed in none or in several. */
export function laneFromPaths(repos: RepoState[], files: string[]): string | undefined {
  const lanes = new Set(files.flatMap((file) => laneForPath(repos, file) ?? []))
  return lanes.size === 1 ? [...lanes][0] : undefined
}
