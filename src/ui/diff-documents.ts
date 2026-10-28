import { basename } from 'node:path'
import * as vscode from 'vscode'
import type { SessionManager } from '../sessions/manager'

export const DIFF_SCHEME = 'agentdeck-diff'

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
    const uri = (side: Side) =>
      vscode.Uri.from({ scheme: DIFF_SCHEME, path: `/${name}`, query: JSON.stringify({ sessionId, itemId, side }) })
    await vscode.commands.executeCommand('vscode.diff', uri('before'), uri('after'), `${name} (agent change)`)
  }
}
