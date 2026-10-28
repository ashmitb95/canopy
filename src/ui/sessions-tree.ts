import * as vscode from 'vscode'
import type { SessionManager } from '../sessions/manager'
import type { SessionStatus } from '../sessions/store'
import { relativeTime } from './time'

export type SessionNode = { id: string; title: string; status: SessionStatus; updatedAt: string; provider: string }

const ICONS: Record<SessionStatus, vscode.ThemeIcon> = {
  idle: new vscode.ThemeIcon('comment'),
  running: new vscode.ThemeIcon('loading~spin'),
  'needs-input': new vscode.ThemeIcon('bell-dot', new vscode.ThemeColor('editorWarning.foreground')),
  error: new vscode.ThemeIcon('error', new vscode.ThemeColor('errorForeground')),
  stopped: new vscode.ThemeIcon('debug-stop')
}

export class SessionsTree implements vscode.TreeDataProvider<SessionNode>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>()
  readonly onDidChangeTreeData = this.changed.event
  private readonly view: vscode.TreeView<SessionNode>
  private readonly subscription: { dispose(): void }

  constructor(
    private readonly manager: SessionManager,
    private readonly labels: ReadonlyMap<string, string>
  ) {
    this.view = vscode.window.createTreeView('agentdeck.sessions', { treeDataProvider: this })
    this.subscription = manager.onDidChange(() => this.refresh())
    this.refresh()
  }

  getChildren(): SessionNode[] {
    return this.manager.list().map(({ record, status }) => ({
      id: record.id,
      title: record.title,
      status,
      updatedAt: record.updatedAt,
      provider: this.labels.get(record.providerId) ?? record.providerId
    }))
  }

  getTreeItem(node: SessionNode): vscode.TreeItem {
    const item = new vscode.TreeItem(node.title)
    item.id = node.id
    item.description = relativeTime(node.updatedAt)
    item.tooltip = `${node.provider} · ${node.status}`
    item.iconPath = ICONS[node.status]
    item.contextValue = 'session'
    item.command = { command: 'agentdeck.openSession', title: 'Open', arguments: [node] }
    return item
  }

  dispose(): void {
    this.subscription.dispose()
    this.view.dispose()
    this.changed.dispose()
  }

  private refresh(): void {
    this.changed.fire()
    const waiting = this.manager.list().filter(({ status }) => status === 'needs-input').length
    this.view.badge = waiting > 0 ? { value: waiting, tooltip: `${waiting} waiting for input` } : undefined
  }
}
