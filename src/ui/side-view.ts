import { basename } from 'node:path'
import * as vscode from 'vscode'
import type { GroupChats } from '../group/chat'
import type { LaneCoordinator } from '../lanes/coordinator'
import { deriveLanes, laneDescription } from '../lanes/lanes'
import { SwitchQuestion } from '../lanes/switch'
import type { LaneTracker } from '../lanes/tracker'
import type { SessionManager } from '../sessions/manager'
import type { HostMessage, LaneCard, SideData, WebviewMessage } from './protocol'
import type { Unread } from './unread'

export const SIDE_VIEW = 'agentdeck.sessions'

/** The primary sidebar (lanes above sessions and group chats) and the full lane view in an editor tab, fed from one place. */
export class SideView implements vscode.WebviewViewProvider, vscode.Disposable {
  private view: vscode.WebviewView | undefined
  private panel: vscode.WebviewPanel | undefined
  private readonly subscriptions: vscode.Disposable[] = []
  private chatListeners: { dispose(): void }[] = []
  private timer: ReturnType<typeof setTimeout> | undefined

  constructor(
    private readonly html: (webview: vscode.Webview, kind: 'side' | 'lanes') => string,
    private readonly roots: () => vscode.Uri[],
    private readonly manager: SessionManager,
    private readonly chats: GroupChats,
    private readonly unread: Unread,
    private readonly tracker: LaneTracker | undefined,
    private readonly lanes: LaneCoordinator | undefined
  ) {
    this.subscriptions.push(
      { dispose: manager.onDidChange(() => this.refresh()).dispose },
      { dispose: unread.onDidChange(() => this.refresh()).dispose },
      ...(tracker ? [{ dispose: tracker.onDidChange(() => this.refresh()).dispose }] : [])
    )
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view
    view.webview.options = { enableScripts: true, localResourceRoots: this.roots() }
    view.webview.html = this.html(view.webview, 'side')
    view.webview.onDidReceiveMessage((message: WebviewMessage) => this.receive(message))
    view.onDidDispose(() => {
      if (this.view === view) this.view = undefined
    })
  }

  /** Opens the full lane view, or reveals it if it is open. */
  openLanes(): void {
    if (this.panel) return this.panel.reveal()
    const panel = vscode.window.createWebviewPanel('agentdeck.lanes', 'Lanes', vscode.ViewColumn.Active, { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: this.roots() })
    panel.webview.html = this.html(panel.webview, 'lanes')
    panel.webview.onDidReceiveMessage((message: WebviewMessage) => this.receive(message))
    panel.onDidDispose(() => {
      this.panel = undefined
    })
    this.panel = panel
  }

  /** Lanes Git shows, plus lanes a chat is on. */
  allLanes() {
    return deriveLanes(this.tracker?.repos ?? [], this.manager.list().flatMap(({ record }) => record.laneId ?? []))
  }

  /** Coalesces bursts of changes into one update. */
  refresh(): void {
    if (this.timer) return
    this.timer = setTimeout(() => {
      this.timer = undefined
      this.post({ type: 'side', side: this.data() })
      if (this.panel) void this.panel.webview.postMessage({ type: 'laneCards', lanes: this.laneCards() } satisfies HostMessage)
    }, 100)
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose()
    for (const listener of this.chatListeners) listener.dispose()
  }

  private data(): SideData {
    // Group chats change often while agents work; listen to each, and pick up new ones on every refresh.
    for (const listener of this.chatListeners) listener.dispose()
    this.chatListeners = this.chats.list().map((chat) => chat.onEvent((event) => event.type === 'state' && this.refresh()))
    const memberIds = new Set(this.chats.list().flatMap((chat) => Object.values(chat.record.members)))
    return {
      lanes: this.tracker
        ? this.allLanes().map((lane) => ({ name: lane.name, where: laneDescription(lane), primary: lane.repos.some((repo) => repo.location === 'primary'), warm: lane.repos.some((repo) => repo.location === 'worktree'), dirty: lane.repos.reduce((sum, repo) => sum + repo.dirty, 0) }))
        : undefined,
      groups: this.chats.list().map((chat) => {
        const state = chat.state()
        const running = state.members.find((member) => member.agent === state.running)
        return {
          id: state.id,
          title: state.title,
          lead: state.lead,
          ...(state.running ? { running: state.running, activity: running?.activity ?? '' } : {}),
          needsYou: state.userQuestions.length > 0 || state.members.some((member) => member.status === 'needs-input') || Boolean(state.blocked),
          agents: state.members.map((member) => member.agent),
          ...(state.laneId ? { laneId: state.laneId } : {})
        }
      }),
      sessions: this.manager
        .list()
        .filter(({ record }) => !memberIds.has(record.id))
        .map(({ record, status }) => ({ id: record.id, title: record.title, providerId: record.providerId, status, updatedAt: record.updatedAt, inTab: false, unread: this.unread.has(record.id), ...(record.laneId ? { laneId: record.laneId } : {}) }))
    }
  }

  private laneCards(): LaneCard[] {
    const side = this.data()
    return this.allLanes().map((lane) => ({
      name: lane.name,
      repos: lane.repos.map((repo) => ({ repo: repo.repo, location: repo.location, dirty: repo.dirty, ...(repo.location === 'worktree' ? { slot: basename(repo.path) } : {}) })),
      chats: [
        ...side.groups
          .filter((group) => group.laneId === lane.name)
          .map((group) => ({ kind: 'group' as const, id: group.id, title: group.title, agents: group.agents, state: group.needsYou ? 'Needs you' : group.running ? `${group.running}: ${group.activity || 'working'}` : `Idle · lead ${group.lead}`, needsYou: group.needsYou })),
        ...side.sessions
          .filter((session) => session.laneId === lane.name)
          .map((session) => ({ kind: 'session' as const, id: session.id, title: session.title, agents: [session.providerId], state: session.status === 'needs-input' ? 'Needs you' : session.status === 'running' ? 'Working' : 'Idle', needsYou: session.status === 'needs-input' }))
      ]
    }))
  }

  private receive(message: WebviewMessage): void {
    this.handle(message).catch((error: unknown) => vscode.window.showErrorMessage(`AgentDeck: ${error instanceof Error ? error.message : String(error)}`))
  }

  private async handle(message: WebviewMessage): Promise<void> {
    switch (message.type) {
      case 'ready':
        this.post({ type: 'side', side: this.data() })
        if (this.panel) void this.panel.webview.postMessage({ type: 'laneCards', lanes: this.laneCards() } satisfies HostMessage)
        return
      case 'openLanes':
        this.openLanes()
        return
      case 'parkLane':
        if (!this.lanes) return
        void vscode.window.showInformationMessage((await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `Moving ${message.laneId} to worktrees…` }, () => this.lanes?.moveToWorktree(message.laneId) ?? Promise.resolve([]))).join(' · '))
        return
      case 'openSession':
        await vscode.commands.executeCommand('agentdeck.openSessionInSidebar', { id: message.sessionId })
        return
      case 'openGroup':
        await vscode.commands.executeCommand('agentdeck.openGroup', message.groupId)
        return
      case 'newGroupChat':
        await vscode.commands.executeCommand('agentdeck.newGroupChat')
        return
      case 'newChat':
        await vscode.commands.executeCommand(message.providerId ? `agentdeck.newChat.${message.providerId}` : 'agentdeck.sidebar.newChat')
        return
      case 'newLane':
        await vscode.commands.executeCommand('agentdeck.newLane')
        return
      case 'reviewLane':
        await vscode.commands.executeCommand('agentdeck.reviewLane', message.laneId)
        return
      case 'switchLane':
        return this.switchLane(message.laneId)
      default:
        return
    }
  }

  /** Moves a lane into the primary checkout, asking the questions preflight raises. */
  private async switchLane(lane: string, answers: { makeLane?: string; takeForeign?: boolean } = {}): Promise<void> {
    if (!this.lanes) return
    try {
      const lines = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `Switching to ${lane}…` }, () => this.lanes?.moveIntoPrimary(lane, answers) ?? Promise.resolve([]))
      void vscode.window.showInformationMessage(lines.join(' · '))
    } catch (error) {
      if (!(error instanceof SwitchQuestion)) throw error
      if (/uncommitted work on/.test(error.message)) {
        const choice = await vscode.window.showWarningMessage(error.message, { modal: true }, 'Make it a lane')
        if (choice !== 'Make it a lane') return
        const name = await vscode.window.showInputBox({ prompt: 'Name the lane for that work', placeHolder: 'my-change' })
        if (name?.trim()) await this.switchLane(lane, { ...answers, makeLane: name.trim() })
        return
      }
      if (/did not create/.test(error.message)) {
        const choice = await vscode.window.showWarningMessage(error.message, { modal: true }, 'Take it')
        if (choice === 'Take it') await this.switchLane(lane, { ...answers, takeForeign: true })
        return
      }
      void vscode.window.showWarningMessage(error.files.length > 0 ? `${error.message} ${error.files.join(', ')}` : error.message)
    }
  }

  private post(message: HostMessage): void {
    void this.view?.webview.postMessage(message)
  }
}
