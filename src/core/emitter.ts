export type Disposable = { dispose(): void }

export type Event<T> = (listener: (value: T) => void) => Disposable

/** A minimal event emitter, so providers and sessions stay free of the vscode module. */
export class Emitter<T> {
  private readonly listeners = new Set<(value: T) => void>()

  readonly event: Event<T> = (listener) => {
    this.listeners.add(listener)
    return { dispose: () => this.listeners.delete(listener) }
  }

  fire(value: T): void {
    for (const listener of [...this.listeners]) listener(value)
  }
}
