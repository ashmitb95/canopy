import type { Memento } from '../src/sessions/store'

/** Stands in for VS Code's workspaceState. */
export class MemoryMemento implements Memento {
  private readonly values = new Map<string, unknown>()

  get<T>(key: string): T | undefined {
    return this.values.get(key) as T | undefined
  }

  async update(key: string, value: unknown): Promise<void> {
    this.values.set(key, structuredClone(value))
  }
}
