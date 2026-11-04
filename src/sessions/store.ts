import type { PermissionMode, SessionFact } from '../core/types'

/** The subset of VS Code's Memento the store uses. */
export interface Memento {
  get<T>(key: string): T | undefined
  update(key: string, value: unknown): PromiseLike<void>
}

export type SessionStatus = 'idle' | 'running' | 'needs-input' | 'error' | 'stopped'

/** Where a chat's lane was (path and HEAD per repo) when the chat last received its lane brief or update. */
export type LaneSeen = { lane: string; at: string; repos: Record<string, { path: string; head?: string }> }

export type SessionRecord = {
  id: string
  providerId: string
  title: string
  createdAt: string
  updatedAt: string
  mode: PermissionMode
  model?: string
  effort?: string
  /** The provider's own session id, used to resume. */
  nativeId?: string
  /** False until a prompt was sent; a provider cannot resume a session it never saved. */
  hasTurns: boolean
  /** Resume up to this provider reference on the next open (set by a rewind). */
  resumeAt?: string
  /** The lane (branch) this chat works on; absent for chats on no lane. */
  laneId?: string
  laneSeen?: LaneSeen
  /** Latest fact of each kind, shown before the CLI is running again. */
  facts: Partial<Record<SessionFact['kind'], SessionFact>>
}

const KEY = 'canopy.sessions'

export class SessionStore {
  constructor(private readonly memento: Memento) {}

  list(): SessionRecord[] {
    return this.all().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  }

  get(id: string): SessionRecord | undefined {
    return this.all().find((record) => record.id === id)
  }

  async put(record: SessionRecord): Promise<void> {
    await this.memento.update(KEY, [...this.all().filter((other) => other.id !== record.id), record])
  }

  async delete(id: string): Promise<void> {
    await this.memento.update(
      KEY,
      this.all().filter((record) => record.id !== id)
    )
  }

  private all(): SessionRecord[] {
    return structuredClone(this.memento.get<SessionRecord[]>(KEY) ?? [])
  }
}
