import type { JSONContent } from '@tiptap/core'

type Store = { get(): unknown; set(value: unknown): void }

/** Unsent drafts per chat, kept in the webview's persisted state next to whatever else is stored there. */
export class Drafts {
  constructor(private readonly store: Store) {}

  load(sessionId: string): JSONContent | undefined {
    return this.all()[sessionId]
  }

  save(sessionId: string, doc: JSONContent | undefined): void {
    const drafts = { ...this.all() }
    if (doc) drafts[sessionId] = doc
    else delete drafts[sessionId]
    const state = this.store.get()
    this.store.set({ ...(typeof state === 'object' && state !== null ? state : {}), drafts })
  }

  private all(): Record<string, JSONContent> {
    const state = this.store.get() as { drafts?: Record<string, JSONContent> } | undefined
    return state?.drafts ?? {}
  }
}
