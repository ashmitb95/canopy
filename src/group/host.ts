import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type { ProviderDefinition } from '../core/types'
import type { Env } from '../env'
import { LaneCoordinator } from '../lanes/coordinator'
import { laneContext } from '../lanes/lane-context'
import { watchHistory, watchTurns } from '../lanes/lane-turns'
import { LaneMemory } from '../lanes/memory'
import { LaneTracker } from '../lanes/tracker'
import { SessionManager } from '../sessions/manager'
import { type Memento, SessionStore } from '../sessions/store'
import { GroupChats } from './chat'

/** Session records in a file, for hosts without VS Code's storage. */
export class FileMemento implements Memento {
  private readonly data: Record<string, unknown>

  constructor(private readonly path: string) {
    this.data = existsSync(path) ? (JSON.parse(readFileSync(path, 'utf8')) as Record<string, unknown>) : {}
  }

  get<T>(key: string): T | undefined {
    return this.data[key] as T | undefined
  }

  async update(key: string, value: unknown): Promise<void> {
    this.data[key] = value
    writeFileSync(`${this.path}.tmp`, JSON.stringify(this.data))
    renameSync(`${this.path}.tmp`, this.path)
  }
}

export type CoreOptions = {
  root: string
  /** Where sessions, journals, and group chats are kept. */
  storage: string
  memento?: Memento
  env: () => Promise<Env>
  providers: ReadonlyMap<string, ProviderDefinition>
}

export type Core = { manager: SessionManager; tracker: LaneTracker; memory: LaneMemory; lanes: LaneCoordinator; chats: GroupChats; dispose(): Promise<void> }

/** Everything AgentDeck does, with no UI: the extension and the terminal driver are both hosts of this. */
export async function createCore(options: CoreOptions): Promise<Core> {
  mkdirSync(options.storage, { recursive: true })
  const tracker = new LaneTracker(options.root)
  await tracker.refresh()
  const memory = new LaneMemory(tracker.root)
  const decorateLane = laneContext(tracker, memory)
  let chats: GroupChats | undefined
  let lanes: LaneCoordinator | undefined
  const manager = new SessionManager({
    providers: options.providers,
    store: new SessionStore(options.memento ?? new FileMemento(join(options.storage, 'sessions.json'))),
    journalDir: join(options.storage, 'sessions'),
    cwd: tracker.root,
    env: options.env,
    // Lane context first, so catch-up sits right before the user's words.
    decorate: async (record, parts) => {
      const withLane = await decorateLane(record, parts)
      return chats ? chats.decorate(record, withLane) : withLane
    },
    boundary: async (record) => lanes?.boundary(record)
  })
  chats = new GroupChats({ manager, providers: options.providers, dir: join(options.storage, 'groups') })
  lanes = new LaneCoordinator({ tracker, memory, manager, env: async () => (await options.env()) as NodeJS.ProcessEnv })
  const watchers = [watchTurns(manager, tracker, memory), watchHistory(tracker, memory)]
  const { chats: readyChats, lanes: readyLanes } = { chats, lanes }
  return {
    manager,
    tracker,
    memory,
    lanes: readyLanes,
    chats: readyChats,
    dispose: async () => {
      for (const watcher of watchers) watcher.dispose()
      readyChats.dispose()
      await manager.dispose()
      tracker.dispose()
    }
  }
}
