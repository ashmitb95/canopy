import { Emitter } from '../src/core/emitter'
import type {
  McpSignIn,
  OpenOptions,
  PermissionMode,
  PromptPart,
  PromptResponse,
  ProviderDefinition,
  ProviderSession,
  Quota,
  SessionFact,
  SessionItem,
  WriteBoundary
} from '../src/core/types'

export class FakeSession implements ProviderSession {
  readonly prompts: PromptPart[][] = []
  readonly answers: [string, PromptResponse][] = []
  readonly modes: PermissionMode[] = []
  readonly efforts: string[] = []
  compacted = 0
  readonly steers: PromptPart[][] = []
  boundaries: (WriteBoundary | undefined)[] = []
  disposed = false
  readonly rewinds: { prompt?: string; keep?: string; files: boolean }[] = []
  restartOnRewind = false
  private readonly items = new Emitter<SessionItem>()
  private readonly facts = new Emitter<SessionFact>()
  private readonly exits = new Emitter<{ error?: string }>()
  readonly onItem = this.items.event
  readonly onFact = this.facts.event
  readonly onExit = this.exits.event
  private readonly quotas = new Emitter<Quota>()
  readonly onQuota = this.quotas.event

  constructor(
    readonly nativeId: string,
    readonly options: OpenOptions
  ) {}

  async prompt(parts: PromptPart[]): Promise<void> {
    this.prompts.push(parts)
  }

  async cancel(): Promise<void> {}

  async setMode(mode: PermissionMode): Promise<void> {
    this.modes.push(mode)
  }

  async setEffort(effort: string): Promise<void> {
    this.efforts.push(effort)
  }

  async compact(): Promise<void> {
    this.compacted++
  }

  async steer(parts: PromptPart[]): Promise<void> {
    this.steers.push(parts)
  }

  answer(itemId: string, response: PromptResponse): void {
    this.answers.push([itemId, response])
  }

  setBoundary(boundary: WriteBoundary | undefined): void {
    this.boundaries.push(boundary)
  }

  async fork(): Promise<string> {
    return `${this.nativeId}-fork`
  }

  async rewind(target: { prompt?: string; keep?: string; files: boolean }): Promise<{ restart?: { resumeAt?: string } }> {
    this.rewinds.push(target)
    return this.restartOnRewind ? { restart: { resumeAt: target.keep } } : {}
  }

  async dispose(): Promise<void> {
    this.disposed = true
    this.exits.fire({})
  }

  quota(quota: Quota): void {
    this.quotas.fire(quota)
  }

  emit(item: SessionItem): void {
    this.items.fire(item)
  }

  fact(fact: SessionFact): void {
    this.facts.fire(fact)
  }

  exit(error?: string): void {
    this.exits.fire({ error })
  }

  async mcpSignIn(server: string): Promise<McpSignIn> {
    return { kind: 'url', url: `https://example.invalid/oauth/${server}` }
  }

  endTurn(): void {
    this.items.fire({ kind: 'turn', id: `turn:${this.nativeId}:${this.prompts.length}`, state: 'ended' })
  }
}

export function fakeProvider(): { provider: ProviderDefinition; sessions: FakeSession[] } {
  const sessions: FakeSession[] = []
  const provider: ProviderDefinition = {
    id: 'fake',
    label: 'Fake',
    cli: { command: 'fake', installUrl: 'https://example.invalid' },
    signInCommand: () => 'fake login',
    capabilities: new Set(['resume', 'interrupt', 'modes', 'setMode']),
    modes: ['ask', 'accept-edits'],
    probe: async () => ({ status: 'signed-in' }),
    open: async (options) => {
      const session = new FakeSession(options.resumeId ?? `native-${sessions.length + 1}`, options)
      sessions.push(session)
      return session
    }
  }
  return { provider, sessions }
}
