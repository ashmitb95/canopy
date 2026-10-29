import { type FSWatcher, realpathSync, watch } from 'node:fs'
import { Emitter } from '../core/emitter'
import { discoverRepos } from './discover'
import { git } from './git'
import { type RepoState, readRepo } from './state'

const DEBOUNCE_MS = 300

/** Files in a git dir whose change can move a branch or a checkout (paths relative to the common git dir). */
const WATCHED = /^(HEAD|packed-refs|refs[\\/]heads([\\/].*)?|worktrees([\\/][^\\/]+([\\/]HEAD)?)?)$/

/** The workspace's repos as Git sees them right now. Re-read when refs move, and when asked. */
export class LaneTracker {
  readonly root: string
  repos: RepoState[] = []
  private readonly changed = new Emitter<void>()
  readonly onDidChange = this.changed.event
  private readonly watchers = new Map<string, FSWatcher>()
  private timer: ReturnType<typeof setTimeout> | undefined
  private chain: Promise<void> = Promise.resolve()
  private last = ''
  private disposed = false

  constructor(root: string) {
    // Git prints real paths; agents' file paths are compared against them.
    this.root = realpathSync(root)
  }

  /** Re-reads every repo; calls run one after another, so awaiting one sees state at least as new as the call. */
  refresh(): Promise<void> {
    this.chain = this.chain.then(
      () => this.read(),
      () => this.read()
    )
    return this.chain
  }

  /** Refreshes once things settle, for bursts of events. */
  schedule(): void {
    clearTimeout(this.timer)
    this.timer = setTimeout(() => void this.refresh().catch(() => {}), DEBOUNCE_MS)
  }

  dispose(): void {
    this.disposed = true
    clearTimeout(this.timer)
    for (const watcher of this.watchers.values()) watcher.close()
    this.watchers.clear()
  }

  private async read(): Promise<void> {
    if (this.disposed) return
    const paths = await discoverRepos(this.root)
    const states = await Promise.all(paths.map((path) => readRepo(this.root, path).catch(() => undefined)))
    if (this.disposed) return
    this.repos = states.filter((state): state is RepoState => state !== undefined)
    await this.watch(this.repos.map((state) => state.path))
    const snapshot = JSON.stringify(this.repos)
    if (snapshot === this.last) return
    this.last = snapshot
    this.changed.fire()
  }

  private async watch(paths: string[]): Promise<void> {
    for (const [path, watcher] of this.watchers) {
      if (paths.includes(path)) continue
      watcher.close()
      this.watchers.delete(path)
    }
    for (const path of paths) {
      if (this.watchers.has(path) || this.disposed) continue
      const dir = (await git(path, ['rev-parse', '--path-format=absolute', '--git-common-dir']).catch(() => '')).trim()
      if (!dir) continue
      const watcher = watch(dir, { recursive: true }, (_event, file) => {
        if (file && WATCHED.test(file.toString())) this.schedule()
      })
      watcher.on('error', () => {
        watcher.close()
        this.watchers.delete(path)
      })
      this.watchers.set(path, watcher)
    }
  }
}
