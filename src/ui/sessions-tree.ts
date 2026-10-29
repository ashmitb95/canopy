import * as vscode from 'vscode'
import { groupSessions } from '../lanes/group'
import { deriveLanes, type Lane, laneDescription } from '../lanes/lanes'
import type { LaneTracker } from '../lanes/tracker'
import type { SessionManager } from '../sessions/manager'
import type { SessionStatus } from '../sessions/store'
import { relativeTime } from './time'

export type SessionNode = {
  kind: 'session'
  id: string
  title: string
  status: SessionStatus
  updatedAt: string
  provider: string
  laneId?: string
}
export type LaneNode = { kind: 'lane'; lane: Lane; sessions: SessionNode[] }
type LooseNode = { kind: 'loose'; sessions: SessionNode[] }
type Node = SessionNode | LaneNode | LooseNode

const ICONS: Record<SessionStatus, vscode.ThemeIcon> = {
  idle: new vscode.ThemeIcon('comment'),
  running: new vscode.ThemeIcon('loading~spin'),
  'needs-input': new vscode.ThemeIcon('bell-dot', new vscode.ThemeColor('editorWarning.foreground')),
  error: new vscode.ThemeIcon('error', new vscode.ThemeColor('errorForeground')),
  stopped: new vscode.ThemeIcon('debug-stop')
}

export class SessionsTree implements vscode.TreeDataProvider<Node>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>()
  readonly onDidChangeTreeData = this.changed.event
  private readonly view: vscode.TreeView<Node>
  private readonly subscriptions: { dispose(): void }[]

  constructor(
    private readonly manager: SessionManager,
    private readonly labels: ReadonlyMap<string, string>,
    private readonly tracker: LaneTracker | undefined
  ) {
    this.view = vscode.window.createTreeView('agentdeck.sessions', { treeDataProvider: this })
    this.subscriptions = [manager.onDidChange(() => this.refresh()), ...(tracker ? [tracker.onDidChange(() => this.refresh())] : [])]
    this.refresh()
  }

  /** Lanes, for *Move to lane…*: every lane Git shows plus every lane a chat is on. */
  lanes(): Lane[] {
    return deriveLanes(this.tracker?.repos ?? [], this.sessions().flatMap((session) => session.laneId ?? []))
  }

  getChildren(element?: Node): Node[] {
    if (element) return element.kind === 'session' ? [] : element.sessions
    const sessions = this.sessions()
    const grouped = groupSessions(this.lanes(), sessions)
    // No lanes in this workspace: the plain list, as before.
    if (grouped.lanes.length === 0) return sessions
    const lanes: Node[] = grouped.lanes.map(({ lane, sessions }) => ({ kind: 'lane', lane, sessions }))
    return grouped.loose.length > 0 ? [...lanes, { kind: 'loose', sessions: grouped.loose }] : lanes
  }

  getTreeItem(node: Node): vscode.TreeItem {
    if (node.kind === 'lane') {
      const item = new vscode.TreeItem(node.lane.name, vscode.TreeItemCollapsibleState.Expanded)
      item.id = `lane:${node.lane.name}`
      item.description = laneDescription(node.lane)
      item.tooltip = node.lane.repos.map((repo) => `${repo.repo}: ${repo.path}`).join('\n') || 'No checkout'
      item.iconPath = new vscode.ThemeIcon('git-branch')
      item.contextValue = 'lane'
      return item
    }
    if (node.kind === 'loose') {
      const item = new vscode.TreeItem('No branch', vscode.TreeItemCollapsibleState.Expanded)
      item.id = 'lane:none'
      item.iconPath = new vscode.ThemeIcon('circle-slash')
      return item
    }
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
    for (const subscription of this.subscriptions) subscription.dispose()
    this.view.dispose()
    this.changed.dispose()
  }

  private sessions(): SessionNode[] {
    return this.manager.list().map(({ record, status }) => ({
      kind: 'session',
      id: record.id,
      title: record.title,
      status,
      updatedAt: record.updatedAt,
      provider: this.labels.get(record.providerId) ?? record.providerId,
      ...(record.laneId ? { laneId: record.laneId } : {})
    }))
  }

  private refresh(): void {
    this.changed.fire()
    const waiting = this.manager.list().filter(({ status }) => status === 'needs-input').length
    this.view.badge = waiting > 0 ? { value: waiting, tooltip: `${waiting} waiting for input` } : undefined
  }
}
