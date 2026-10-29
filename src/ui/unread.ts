import * as vscode from 'vscode'

const KEY = 'agentdeck.unread'

/** Chats whose turn ended (or failed) while they were out of sight, until shown again. */
export class Unread {
  private readonly changed = new vscode.EventEmitter<void>()
  readonly onDidChange = this.changed.event

  constructor(private readonly memento: vscode.Memento) {}

  has(id: string): boolean {
    return this.all().includes(id)
  }

  mark(id: string): void {
    if (this.has(id)) return
    void this.memento.update(KEY, [...this.all(), id]).then(() => this.changed.fire())
  }

  clear(id: string): void {
    if (!this.has(id)) return
    void this.memento.update(KEY, this.all().filter((other) => other !== id)).then(() => this.changed.fire())
  }

  private all(): string[] {
    return this.memento.get<string[]>(KEY) ?? []
  }
}
