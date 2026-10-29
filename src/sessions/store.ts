import type { PermissionMode, SessionFact } from '../core/types'

/** The subset of VS Code's Memento the store uses. */
export interface Memento {
  get<T>(key: string): T | undefined
  update(key: string, value: unknown): PromiseLike<void>
}

export type SessionStatus = 'idle' | 'running' | 'needs-input' | 'error' | 'stopped'

export type SessionRecord = {
  id: string
  providerId: string
  title: string
  createdAt: string
  updatedAt: string
  mode: PermissionMode
  model?: string
  /** The provider's own session id, used to resume. */
  nativeId?: string
  /** False until a prompt was sent; a provider cannot resume a session it never saved. */
  hasTurns: boolean
  /** The lane (branch) this chat works on; absent for chats on no lane. */
  laneId?: string
  /** Latest fact of each kind, shown before the CLI is running again. */
  facts: Partial<Record<SessionFact['kind'], SessionFact>>
}

const KEY = 'agentdeck.sessions'

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
