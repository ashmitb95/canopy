import { join, relative, sep } from 'node:path'
import type { WriteBoundary } from '../core/types'
import type { SessionManager } from '../sessions/manager'
import type { SessionRecord } from '../sessions/store'
import { readConfig } from './config'
import { deriveLanes } from './lanes'
import type { LaneMemory } from './memory'
import type { RepoState } from './state'
import { joinRepo, moveIntoPrimary, moveToWorktree, SwitchError } from './switch'
import type { LaneTracker } from './tracker'
import { warmUp } from './warmup'

export type CoordinatorDeps = {
  tracker: LaneTracker
  memory: LaneMemory
  manager: SessionManager
  /** The environment setup commands run in (the user's login shell environment). */
  env: () => Promise<NodeJS.ProcessEnv>
}

const inside = (root: string, path: string) => path === root || path.startsWith(root + sep)

/** Moves lanes on request and draws each chat's write boundary. Agents never call it; the app does. */
export class LaneCoordinator {
  constructor(private readonly deps: CoordinatorDeps) {}

  /** Creates a lane in the given repos, in worktrees (warmed up) or in the primary checkouts. */
  async newLane(name: string, repoNames: string[], options: { worktrees: boolean; goal?: string }): Promise<void> {
    const { tracker, memory } = this.deps
    memory.ensure(name)
    memory.setWorktrees(name, options.worktrees)
    if (options.goal) memory.setGoal(name, options.goal)
    await tracker.refresh()
    for (const repo of tracker.repos.filter((candidate) => repoNames.includes(candidate.name))) {
      const path = await joinRepo(repo, name, options.worktrees)
      if (path !== repo.path) await this.warm(repo, name, path)
    }
    await tracker.refresh()
  }

  /** Brings the lane into the primary checkout of every repo it is in; lanes there move to worktrees and are warmed up. */
  async moveIntoPrimary(lane: string): Promise<string[]> {
    const { tracker } = this.deps
    await tracker.refresh()
    const repos = this.reposOf(lane)
    if (repos.length === 0) throw new SwitchError(`${lane} has no checkout to move.`)
    const holders = repos.flatMap((repo) => {
      const branch = repo.checkouts.find((checkout) => checkout.primary)?.branch
      return branch && branch !== repo.base && branch !== lane ? [branch] : []
    })
    this.assertIdle([lane, ...holders])
    const lines: string[] = []
    for (const repo of repos) {
      const result = await moveIntoPrimary(repo, lane)
      lines.push(`${lane} moved to the primary checkout of ${repo.name}/`)
      if (result.movedOut && result.worktree) {
        lines.push(`${result.movedOut} moved to ${this.rel(result.worktree)}`)
        void this.warm(repo, result.movedOut, result.worktree)
      }
    }
    await this.settle([lane, ...holders], lines)
    return lines
  }

  /** Moves the lane out of every primary checkout it holds; the base branch goes back in. */
  async moveToWorktree(lane: string): Promise<string[]> {
    const { tracker } = this.deps
    await tracker.refresh()
    const repos = tracker.repos.filter((repo) => repo.checkouts.some((checkout) => checkout.primary && checkout.branch === lane))
    if (repos.length === 0) throw new SwitchError(`${lane} holds no primary checkout.`)
    this.assertIdle([lane])
    const lines: string[] = []
    for (const repo of repos) {
      const path = await moveToWorktree(repo, lane)
      lines.push(`${lane} moved to ${this.rel(path)}`)
      void this.warm(repo, lane, path)
    }
    await this.settle([lane], lines)
    return lines
  }

  /** Where a chat on a lane may write: the lane's checkouts and its memory folder. */
  async boundary(record: SessionRecord): Promise<WriteBoundary | undefined> {
    const name = record.laneId
    if (!name) return undefined
    const { tracker, memory } = this.deps
    const lane = deriveLanes(tracker.repos, [name]).find((candidate) => candidate.name === name)
    if (!lane) return undefined
    const roots = [...lane.repos.map((repo) => repo.path), memory.laneDir(name)]
    const except = tracker.repos
      .flatMap((repo) => repo.checkouts.map((checkout) => checkout.path))
      .filter((path) => !roots.includes(path) && roots.some((root) => inside(root, path)))
    return { roots, except, outside: (path) => this.redirect(name, path) }
  }

  /** Explains a refused write: same file in the lane's own checkout, or join the repo first. */
  private async redirect(lane: string, path: string): Promise<string> {
    const { tracker, memory } = this.deps
    const repo = [...tracker.repos].sort((a, b) => b.path.length - a.path.length).find((candidate) => inside(candidate.path, path))
    const checkout = repo?.checkouts
      .filter((candidate) => inside(candidate.path, path))
      .sort((a, b) => b.path.length - a.path.length)[0]
    if (!repo || !checkout) return `${this.rel(path)} is outside lane ${lane} and every repo AgentDeck tracks. Edit only inside the lane's paths.`
    const within = relative(checkout.path, path)
    const own = repo.checkouts.find((candidate) => candidate.branch === lane)
    if (own) return `${this.rel(path)} is outside lane ${lane}. Make this edit at ${this.rel(join(own.path, within))} instead.`
    const worktrees = memory.worktrees(lane) ?? readConfig(tracker.root).worktrees
    try {
      const joined = await joinRepo(repo, lane, worktrees)
      if (joined !== repo.path) void this.warm(repo, lane, joined)
      await this.settle([lane], [`${lane} joined ${repo.name}`])
      return `${repo.name} joined lane ${lane} at ${this.rel(joined)}. Make this edit at ${this.rel(join(joined, within))} instead.`
    } catch (error) {
      return `${this.rel(path)} is outside lane ${lane}, and ${repo.name} could not join it: ${(error as Error).message}`
    }
  }

  private async warm(repo: RepoState, lane: string, path: string): Promise<void> {
    const { tracker, memory, manager } = this.deps
    const config = readConfig(tracker.root)
    const primary = repo.checkouts.find((checkout) => checkout.primary)?.path ?? repo.path
    const result = await warmUp(primary, path, config.envFiles, config.setup[repo.name], await this.deps.env())
    memory.appendHistory(lane, { event: 'warmed', repo: repo.name, copied: result.copied, ok: result.setup?.ok ?? true })
    if (result.setup && !result.setup.ok) {
      for (const record of this.chatsOn([lane])) {
        manager.notify(record.id, `Warm-up of ${lane} in ${repo.name} failed: ${result.setup.command}\n${result.setup.output}`, 'warning')
      }
    }
  }

  private reposOf(lane: string): RepoState[] {
    return this.deps.tracker.repos.filter((repo) => repo.checkouts.some((checkout) => checkout.branch === lane))
  }

  private assertIdle(lanes: string[]): void {
    const busy = this.deps.manager.busyOn(lanes)
    if (busy.length > 0) {
      throw new SwitchError(`Waiting for ${busy.map((record) => `“${record.title}”`).join(', ')} to finish its turn. Try again then, or stop it.`)
    }
  }

  private chatsOn(lanes: string[]): SessionRecord[] {
    return this.deps.manager
      .list()
      .map(({ record }) => record)
      .filter((record) => record.laneId !== undefined && lanes.includes(record.laneId))
  }

  /** After a move: re-read Git, record history, and tell every affected chat in one line. */
  private async settle(lanes: string[], lines: string[]): Promise<void> {
    await this.deps.tracker.refresh()
    for (const lane of lanes) this.deps.memory.appendHistory(lane, { event: 'switched', lines })
    for (const record of this.chatsOn(lanes)) this.deps.manager.notify(record.id, `↪ ${lines.join(' · ')}`)
  }

  private rel(path: string): string {
    return relative(this.deps.tracker.root, path) || '.'
  }
}
