import { basename } from 'node:path'
import * as vscode from 'vscode'
import type { SessionManager } from '../sessions/manager'

export const DIFF_SCHEME = 'canopy-diff'

type Side = 'before' | 'after'

/** Serves the two sides of a diff item, so VS Code's diff editor can show it. */
export class DiffDocuments implements vscode.TextDocumentContentProvider {
  constructor(private readonly manager: SessionManager) {}

  provideTextDocumentContent(uri: vscode.Uri): string {
    const { sessionId, itemId, side } = JSON.parse(uri.query) as { sessionId: string; itemId: string; side: Side }
    const item = this.manager.item(sessionId, itemId)
    if (item?.kind !== 'diff') return ''
    return side === 'before' ? (item.oldText ?? '') : item.newText
  }

  async open(sessionId: string, itemId: string): Promise<void> {
    const item = this.manager.item(sessionId, itemId)
    if (item?.kind !== 'diff') return
    const name = basename(item.path)
    await vscode.commands.executeCommand('vscode.diff', this.uri(sessionId, itemId, name, 'before'), this.uri(sessionId, itemId, name, 'after'), `${name} (agent change)`)
  }

  /** Several diffs at once, in VS Code's multi-diff editor. */
  async openAll(sessionId: string, itemIds: string[]): Promise<void> {
    if (itemIds.length === 1) return this.open(sessionId, itemIds[0])
    const resources = itemIds.flatMap((itemId) => {
      const item = this.manager.item(sessionId, itemId)
      if (item?.kind !== 'diff') return []
      const name = basename(item.path)
      return [[vscode.Uri.file(item.path), this.uri(sessionId, itemId, name, 'before'), this.uri(sessionId, itemId, name, 'after')]]
    })
    await vscode.commands.executeCommand('vscode.changes', 'Agent changes', resources)
  }

  private uri(sessionId: string, itemId: string, name: string, side: Side): vscode.Uri {
    return vscode.Uri.from({ scheme: DIFF_SCHEME, path: `/${name}`, query: JSON.stringify({ sessionId, itemId, side }) })
  }
}
