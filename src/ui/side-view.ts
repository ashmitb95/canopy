import { execFile } from 'node:child_process'
import { basename, relative } from 'node:path'
import * as vscode from 'vscode'
import type { GroupChats } from '../group/chat'
import type { LaneCoordinator } from '../lanes/coordinator'
import { deriveLanes, type Lane, laneDescription } from '../lanes/lanes'
import type { LaneMemory } from '../lanes/memory'
import { SwitchQuestion } from '../lanes/switch'
import type { LaneTracker } from '../lanes/tracker'
import type { SessionManager } from '../sessions/manager'
import type { HostMessage, LaneCard, SideData, WebviewMessage } from './protocol'
import { relativeTime } from './time'
import type { Unread } from './unread'

export const SIDE_VIEW = 'canopy.sessions'
/** Every conversation, in its own view in the secondary sidebar. */
export const CONVERSATIONS_VIEW = 'canopy.conversations'
export const LANES_PANEL = 'canopy.lanes'

/**
 * The primary sidebar (lanes above sessions and group chats), the conversations list, and the full lane view in an
 * editor tab, fed from one place.
 */
export class SideView implements vscode.WebviewViewProvider, vscode.WebviewPanelSerializer, vscode.Disposable {
  private readonly views = new Set<vscode.WebviewView>()
  private panel: vscode.WebviewPanel | undefined
  private readonly subscriptions: vscode.Disposable[] = []
  private chatListeners: { dispose(): void }[] = []
  private timer: ReturnType<typeof setTimeout> | undefined
  private readonly laneListeners = new Set<() => void>()

  constructor(
    private readonly html: (webview: vscode.Webview, kind: 'side' | 'lanes' | 'conversations') => string,
    private readonly roots: () => vscode.Uri[],
    private readonly manager: SessionManager,
    private readonly chats: GroupChats,
    private readonly unread: Unread,
    private readonly tracker: LaneTracker | undefined,
    private readonly lanes: LaneCoordinator | undefined,
    private readonly memory: LaneMemory | undefined
  ) {
    this.subscriptions.push(
      { dispose: manager.onDidChange(() => this.refresh()).dispose },
      { dispose: unread.onDidChange(() => this.refresh()).dispose },
      ...(tracker ? [{ dispose: tracker.onDidChange(() => this.refresh()).dispose }] : [])
    )
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    this.views.add(view)
    view.webview.options = { enableScripts: true, localResourceRoots: this.roots() }
    view.webview.html = this.html(view.webview, view.viewType === CONVERSATIONS_VIEW ? 'conversations' : 'side')
    view.webview.onDidReceiveMessage((message: WebviewMessage) => this.receive(message))
    view.onDidDispose(() => this.views.delete(view))
  }

  /** Opens the full lane view, or reveals it if it is open. */
  openLanes(): void {
    if (this.panel) return this.panel.reveal()
    this.adoptLanes(vscode.window.createWebviewPanel(LANES_PANEL, 'Lanes', vscode.ViewColumn.Active, { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: this.roots() }))
  }

  /** A lane tab VS Code restored after a reload. */
  async deserializeWebviewPanel(panel: vscode.WebviewPanel): Promise<void> {
    if (this.panel) return panel.dispose()
    this.adoptLanes(panel)
  }

  private adoptLanes(panel: vscode.WebviewPanel): void {
    panel.webview.options = { enableScripts: true, localResourceRoots: this.roots() }
    panel.webview.html = this.html(panel.webview, 'lanes')
    panel.webview.onDidReceiveMessage((message: WebviewMessage) => this.receive(message))
    panel.onDidDispose(() => {
      if (this.panel === panel) this.panel = undefined
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
      this.postLanes()
      for (const listener of this.laneListeners) listener()
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

  /** Called when lanes or the chats on them change, for other views that show lane cards. */
  onLanesChanged(listener: () => void): { dispose(): void } {
    this.laneListeners.add(listener)
    return { dispose: () => this.laneListeners.delete(listener) }
  }

  /** Runs a lane action from another view that shows lane cards; false for anything else. */
  async handleLane(message: WebviewMessage): Promise<boolean> {
    if (!['switchLane', 'parkLane', 'warmUpLane', 'openLaneChat', 'reviewLane', 'newLane', 'openLanes'].includes(message.type)) return false
    await this.handle(message)
    return true
  }

  async laneCards(): Promise<LaneCard[]> {
    const side = this.data()
    const root = this.tracker?.root ?? ''
    const card = (name: string, place: LaneCard['place'], repos: Lane['repos']): LaneCard => {
      const groups = side.groups.filter((group) => group.laneId === name)
      const sessions = side.sessions.filter((session) => session.laneId === name)
      const needs = groups.find((group) => group.needsYou)
      const working = groups.find((group) => group.running)
      const session = sessions.find((candidate) => candidate.status === 'needs-input') ?? sessions.find((candidate) => candidate.status === 'running') ?? sessions[0]
      const status: LaneCard['status'] = needs
        ? { agent: needs.running ?? needs.lead, text: 'Needs you', tone: 'needs' }
        : working?.running
          ? { agent: working.running, text: `Working${working.activity ? ` · ${working.activity}` : ''}`, tone: 'working' }
          : session
            ? { agent: session.providerId, text: session.status === 'needs-input' ? 'Needs you' : session.status === 'running' ? 'Working' : `${session.unread ? 'Finished' : 'Idle'} · ${relativeTime(session.updatedAt)}`, tone: session.status === 'needs-input' ? 'needs' : session.status === 'running' ? 'working' : session.unread ? 'done' : 'idle' }
            : groups[0]
              ? { agent: groups[0].lead, text: 'Idle', tone: 'idle' }
              : undefined
      const goal = this.memory?.goal(name)
      return {
        name,
        ...(goal ? { goal } : {}),
        place,
        paths: repos.filter((repo) => repo.location === 'worktree').map((repo) => relative(root, repo.path) || basename(repo.path)),
        dirty: repos.reduce((sum, repo) => sum + repo.dirty, 0),
        chats: groups.length + sessions.length,
        ...(status ? { status } : {})
      }
    }
    const lanes = this.allLanes()
    const cards = lanes.map((lane) => card(lane.name, lane.repos.some((repo) => repo.location === 'primary') ? 'primary' : lane.repos.length > 0 ? 'warm' : 'cold', lane.repos))
    const known = new Set(lanes.map((lane) => lane.name))
    for (const name of this.memory?.lanes() ?? []) if (!known.has(name)) cards.push(card(name, 'cold', []))
    const primary = lanes.find((lane) => lane.repos.some((repo) => repo.location === 'primary'))
    const primaryCard = cards.find((candidate) => candidate.place === 'primary')
    if (primary && primaryCard) primaryCard.shared = await this.shared(primary)
    return cards
  }

  /** Files the primary checkout's lane changed from the base branch, committed or not. */
  private async shared(lane: Lane): Promise<LaneCard['shared']> {
    const files: NonNullable<LaneCard['shared']> = []
    for (const laneRepo of lane.repos.filter((repo) => repo.location === 'primary')) {
      const base = this.tracker?.repos.find((repo) => repo.name === laneRepo.repo)?.base
      if (!base) continue
      const out = await new Promise<string>((resolve) => execFile('git', ['diff', '--numstat', base], { cwd: laneRepo.path, maxBuffer: 8 * 1024 * 1024 }, (error, stdout) => resolve(error ? '' : stdout)))
      for (const row of out.split('\n').filter(Boolean)) {
        const [added, removed, path] = row.split('\t')
        files.push({ path: lane.repos.length > 1 ? `${laneRepo.repo}/${path}` : path, added: Number(added) || 0, removed: Number(removed) || 0 })
      }
    }
    return files
  }

  private postLanes(): void {
    const panel = this.panel
    if (panel) void this.laneCards().then((lanes) => panel.webview.postMessage({ type: 'laneCards', lanes } satisfies HostMessage))
  }

  private receive(message: WebviewMessage): void {
    this.handle(message).catch((error: unknown) => vscode.window.showErrorMessage(`Canopy: ${error instanceof Error ? error.message : String(error)}`))
  }

  private async handle(message: WebviewMessage): Promise<void> {
    switch (message.type) {
      case 'ready':
        this.post({ type: 'side', side: this.data() })
        this.postLanes()
        return
      case 'openLanes':
        this.openLanes()
        return
      case 'parkLane':
        return this.move(`Parking ${message.laneId}…`, (lanes) => lanes.park(message.laneId))
      case 'warmUpLane':
        return this.move(`Warming up ${message.laneId}…`, (lanes) => lanes.warmUp(message.laneId))
      case 'openLaneChat': {
        const group = this.chats.list().find((chat) => chat.record.laneId === message.laneId)
        if (group) return void (await vscode.commands.executeCommand('canopy.openGroup', group.record.id))
        const session = this.manager.list().find(({ record }) => record.laneId === message.laneId)
        if (session) return void (await vscode.commands.executeCommand('canopy.openSessionInSidebar', { id: session.record.id }))
        await vscode.commands.executeCommand('canopy.newGroupChat', { laneId: message.laneId, title: this.memory?.goal(message.laneId) ?? message.laneId })
        return
      }
      case 'openSession':
        await vscode.commands.executeCommand('canopy.openSessionInSidebar', { id: message.sessionId })
        return
      case 'openGroup':
        await vscode.commands.executeCommand('canopy.openGroup', message.groupId)
        return
      case 'newGroupChat':
        await vscode.commands.executeCommand('canopy.newGroupChat')
        return
      case 'newChat':
        await vscode.commands.executeCommand(message.providerId ? `canopy.newChat.${message.providerId}` : 'canopy.sidebar.newChat')
        return
      case 'newLane':
        await vscode.commands.executeCommand('canopy.newLane')
        return
      case 'reviewLane':
        await vscode.commands.executeCommand('canopy.reviewLane', message.laneId)
        return
      case 'switchLane':
        return this.switchLane(message.laneId)
      default:
        return
    }
  }

  private async move(title: string, run: (lanes: LaneCoordinator) => Promise<string[]>): Promise<void> {
    const lanes = this.lanes
    if (!lanes) return
    const lines = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title }, () => run(lanes))
    void vscode.window.showInformationMessage(lines.join(' · '))
  }

  /** Moves a lane into the primary checkout, asking the questions preflight raises. */
  async switchLane(lane: string, answers: { makeLane?: string; takeForeign?: boolean } = {}): Promise<void> {
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
    for (const view of this.views) void view.webview.postMessage(message)
  }
}
