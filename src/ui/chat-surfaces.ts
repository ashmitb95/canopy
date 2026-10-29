import { randomBytes } from 'node:crypto'
import { join } from 'node:path'
import * as vscode from 'vscode'
import type { Disposable, Event } from '../core/emitter'
import type { PromptPart, ProviderDefinition, ProviderState, Quota, SignInFlow } from '../core/types'
import type { Env } from '../env'
import type { Attention, SessionManager } from '../sessions/manager'
import { attachFile, saveImage } from './attachments'
import type { DiffDocuments } from './diff-documents'
import type { EditorContextTracker } from './editor-context'
import { FileSearch } from './file-search'
import type { HostMessage, LaneInfo, ProviderInfo, SignInProgress, WebviewMessage } from './protocol'

export const PANEL_TYPE = 'agentdeck.chatPanel'
export const SIDEBAR_VIEW = 'agentdeck.chat'
const SIDEBAR_SESSION_KEY = 'agentdeck.sidebarSession'
const QUOTA_KEY = 'agentdeck.quota'
const DEFAULT_PROVIDER = 'claude'

/** Lanes for the chat's lane chip; absent when no folder is open. */
export type LaneSource = { list(): LaneInfo[]; onDidChange: Event<void> }

type SurfaceKind = 'panel' | 'view'

/** One webview showing one session at a time. */
type Surface = {
  readonly webview: vscode.Webview
  readonly kind: SurfaceKind
  panel?: vscode.WebviewPanel
  sessionId?: string
  subscription?: Disposable
  listener?: vscode.Disposable
}

/** Editor tabs and the sidebar chat. Each subscribes to a session and relays its events. */
export class ChatSurfaces
  implements vscode.WebviewViewProvider, vscode.WebviewPanelSerializer<{ sessionId?: string }>, vscode.Disposable
{
  private readonly panels = new Map<string, { panel: vscode.WebviewPanel; surface: Surface }>()
  private sidebar: Surface | undefined
  /** Editor tabs showing the provider chooser, before a session exists. */
  private readonly blankPanels = new Set<Surface>()
  private sidebarView: vscode.WebviewView | undefined
  /** Latest usage per provider; kept across reloads and shown with its age. */
  private readonly quotas: Record<string, Quota>
  private readonly states = new Map<string, ProviderState>()
  private readonly signIns = new Map<string, { flow?: SignInFlow; progress: SignInProgress }>()
  private readonly subscriptions: { dispose(): void }[] = []
  private readonly files = new FileSearch()
  private readonly attachmentsDir: string

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly manager: SessionManager,
    private readonly providers: ReadonlyMap<string, ProviderDefinition>,
    private readonly env: () => Promise<Env>,
    private readonly editor: EditorContextTracker,
    private readonly diffs: DiffDocuments,
    private readonly lanes?: LaneSource
  ) {
    this.attachmentsDir = join((context.storageUri ?? context.globalStorageUri).fsPath, 'attachments')
    this.quotas = context.globalState.get<Record<string, Quota>>(QUOTA_KEY) ?? {}
    this.subscriptions.push(
      manager.onDidChange(() => {
        this.refreshTitles()
        this.postSessions()
        this.postLanes()
      }),
      ...(lanes ? [lanes.onDidChange(() => this.postLanes())] : []),
      editor.onDidChange((editorContext) => this.broadcast({ type: 'editorContext', context: editorContext })),
      manager.onQuota(({ providerId, quota }) => {
        this.quotas[providerId] = quota
        void this.context.globalState.update(QUOTA_KEY, this.quotas)
        this.broadcast({ type: 'quota', providerId, quota })
      }),
      manager.onAttention((event) => this.attend(event))
    )
  }

  /** Starts a chat with a provider, or shows the in-app provider chooser when none is given. */
  async newChat(where: SurfaceKind, providerId?: string): Promise<void> {
    if (providerId) {
      const record = await this.manager.create(providerId)
      if (where === 'panel') this.openPanel(record.id)
      else await this.showInSidebar(record.id)
      return
    }
    if (where === 'panel') return this.openBlankPanel()
    await this.context.workspaceState.update(SIDEBAR_SESSION_KEY, undefined)
    await vscode.commands.executeCommand(`${SIDEBAR_VIEW}.focus`)
    if (this.sidebar) this.clear(this.sidebar)
  }

  private openBlankPanel(): void {
    const panel = vscode.window.createWebviewPanel(PANEL_TYPE, 'New chat', vscode.ViewColumn.Beside, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: this.roots()
    })
    this.attachPanel(panel)
  }

  /** The provider chooser in its own tab: the welcome screen and the providers page. */
  openProviders(title = 'AgentDeck: Providers'): void {
    const panel = vscode.window.createWebviewPanel(PANEL_TYPE, title, vscode.ViewColumn.Active, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: this.roots()
    })
    this.attachPanel(panel)
    panel.title = title
  }

  private clear(surface: Surface): void {
    surface.subscription?.dispose()
    surface.subscription = undefined
    surface.sessionId = undefined
    this.post(surface, { type: 'empty' })
  }

  /** A chat started from a surface's chooser opens in that surface. */
  private async startIn(surface: Surface, providerId: string): Promise<void> {
    const record = await this.manager.create(providerId)
    if (surface.kind === 'view') return this.showInSidebar(record.id)
    if (surface.sessionId || !surface.panel) return this.openPanel(record.id)
    this.blankPanels.delete(surface)
    this.panels.set(record.id, { panel: surface.panel, surface })
    surface.panel.title = this.title(record.id)
    this.show(surface, record.id)
  }

  openPanel(sessionId: string): void {
    const open = this.panels.get(sessionId)
    if (open) return open.panel.reveal()
    const panel = vscode.window.createWebviewPanel(PANEL_TYPE, this.title(sessionId), vscode.ViewColumn.Beside, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: this.roots()
    })
    this.attachPanel(panel, sessionId)
  }

  async showInSidebar(sessionId: string): Promise<void> {
    await this.context.workspaceState.update(SIDEBAR_SESSION_KEY, sessionId)
    await vscode.commands.executeCommand(`${SIDEBAR_VIEW}.focus`)
    if (this.sidebar) this.show(this.sidebar, sessionId)
  }

  /** The chat in the focused tab, else the sidebar's chat. */
  activeSessionId(): string | undefined {
    for (const [sessionId, { panel }] of this.panels) if (panel.active) return sessionId
    return this.sidebar?.sessionId
  }

  openSidebarInEditor(): void {
    if (this.sidebar?.sessionId) this.openPanel(this.sidebar.sessionId)
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    view.webview.options = { enableScripts: true, localResourceRoots: this.roots() }
    view.webview.html = this.html(view.webview, 'view')
    const surface = this.surface(view.webview, 'view', this.sidebarSession())
    this.sidebar = surface
    this.sidebarView = view
    view.onDidDispose(() => {
      this.release(surface)
      if (this.sidebar === surface) {
        this.sidebar = undefined
        this.sidebarView = undefined
      }
    })
  }

  async deserializeWebviewPanel(panel: vscode.WebviewPanel, state: { sessionId?: string } | undefined): Promise<void> {
    if (!state?.sessionId || !this.exists(state.sessionId)) return panel.dispose()
    this.attachPanel(panel, state.sessionId)
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose()
    this.files.dispose()
    for (const { flow } of this.signIns.values()) flow?.cancel()
    for (const { surface } of this.panels.values()) this.release(surface)
    for (const surface of this.blankPanels) this.release(surface)
    if (this.sidebar) this.release(this.sidebar)
  }

  private attachPanel(panel: vscode.WebviewPanel, sessionId?: string): void {
    panel.webview.options = { enableScripts: true, localResourceRoots: this.roots() }
    panel.webview.html = this.html(panel.webview, 'panel')
    panel.title = sessionId ? this.title(sessionId) : 'New chat'
    const surface = this.surface(panel.webview, 'panel', sessionId)
    surface.panel = panel
    if (sessionId) this.panels.set(sessionId, { panel, surface })
    else this.blankPanels.add(surface)
    panel.onDidDispose(() => {
      this.release(surface)
      if (surface.sessionId) this.panels.delete(surface.sessionId)
      this.blankPanels.delete(surface)
    })
  }

  private surface(webview: vscode.Webview, kind: SurfaceKind, sessionId: string | undefined): Surface {
    const surface: Surface = { webview, kind, sessionId }
    surface.listener = webview.onDidReceiveMessage((message: WebviewMessage) =>
      this.handle(surface, message).catch((error: unknown) =>
        vscode.window.showErrorMessage(`AgentDeck: ${error instanceof Error ? error.message : String(error)}`)
      )
    )
    return surface
  }

  private release(surface: Surface): void {
    surface.subscription?.dispose()
    surface.listener?.dispose()
  }

  /** The webview may load the bundle and attached images. */
  private roots(): vscode.Uri[] {
    return [this.assets(), vscode.Uri.file(this.attachmentsDir)]
  }

  private reply(surface: Surface, requestId: number, value: unknown): void {
    this.post(surface, { type: 'reply', requestId, value })
  }

  private async handle(surface: Surface, message: WebviewMessage): Promise<void> {
    const sessionId = surface.sessionId
    switch (message.type) {
      case 'ready':
        this.post(surface, { type: 'editorContext', context: this.editor.current() })
        this.post(surface, {
          type: 'assets',
          attachments: surface.webview.asWebviewUri(vscode.Uri.file(this.attachmentsDir)).toString()
        })
        this.postSessions(surface)
        this.postLanes(surface)
        await this.postProviders(surface)
        for (const [providerId, quota] of Object.entries(this.quotas)) this.post(surface, { type: 'quota', providerId, quota })
        for (const [providerId, { progress }] of this.signIns) this.post(surface, { type: 'signInProgress', providerId, progress })
        if (sessionId) this.show(surface, sessionId)
        else this.post(surface, { type: 'empty' })
        return
      case 'prompt': {
        const target = sessionId ?? (await this.createFor(surface))
        const parts: PromptPart[] = [...message.parts]
        const file = message.includeContext ? this.editor.part() : null
        if (file) parts.push(file)
        return this.manager.prompt(target, parts)
      }
      case 'cancel':
        if (sessionId) await this.manager.cancel(sessionId)
        return
      case 'answer':
        if (sessionId) this.manager.answer(sessionId, message.itemId, message.response)
        return
      case 'removeQueued':
        if (sessionId) this.manager.removeQueued(sessionId, message.queuedId)
        return
      case 'newChat':
        if (message.providerId) return this.startIn(surface, message.providerId)
        return this.newChat(surface.kind)
      case 'signIn':
        return this.signIn(surface, message.providerId)
      case 'setModel':
        if (sessionId) await this.manager.setModel(sessionId, message.model)
        return
      case 'setMode':
        if (sessionId) await this.manager.setMode(sessionId, message.mode)
        return
      case 'refreshMcp':
        if (sessionId) await this.manager.refreshMcp(sessionId)
        return
      case 'reconnectMcp':
        if (sessionId) await this.manager.reconnectMcp(sessionId, message.server)
        return
      case 'mcpSignIn':
        return this.mcpSignIn(surface, message.server, message.scope)
      case 'openDiff':
        if (sessionId) await this.diffs.open(sessionId, message.itemId)
        return
      case 'switchSession':
        if (surface.kind === 'view') await this.showInSidebar(message.sessionId)
        else this.openPanel(message.sessionId)
        return
      case 'reviewChanges':
        if (sessionId) await this.diffs.openAll(sessionId, message.itemIds)
        return
      case 'setLane':
        if (sessionId) await this.manager.setLane(sessionId, message.laneId)
        return
      case 'handOff':
        if (sessionId) await vscode.commands.executeCommand('agentdeck.handOff', sessionId)
        return
      case 'newLane':
        await vscode.commands.executeCommand('agentdeck.newLane')
        return
      case 'reviewLane':
        await vscode.commands.executeCommand('agentdeck.reviewLane', message.laneId)
        return
      case 'openSession':
        this.openPanel(message.sessionId)
        return
      case 'cancelSignIn':
        this.signIns.get(message.providerId)?.flow?.cancel()
        this.setSignIn(message.providerId, null)
        return
      case 'signInInTerminal':
        return this.signInInTerminal(surface, message.providerId)
      case 'refreshProviders':
        this.states.clear()
        return this.postProviders()
      case 'searchFiles':
        return this.reply(surface, message.requestId, await this.files.search(message.query))
      case 'pickAttachments': {
        const uris = await vscode.window.showOpenDialog({ canSelectMany: true, openLabel: 'Attach' })
        const attachments = (uris ?? []).map((uri) => attachFile(this.attachmentsDir, uri.fsPath, vscode.workspace.asRelativePath(uri)))
        return this.reply(surface, message.requestId, attachments)
      }
      case 'saveImage':
        return this.reply(
          surface,
          message.requestId,
          saveImage(this.attachmentsDir, message.name, message.mimeType, Buffer.from(message.data, 'base64'))
        )
      case 'openFile': {
        const document = await vscode.workspace.openTextDocument(message.path)
        const line = Math.max((message.line ?? 1) - 1, 0)
        await vscode.window.showTextDocument(document, {
          viewColumn: vscode.ViewColumn.One,
          selection: new vscode.Range(line, 0, line, 0)
        })
        return
      }
    }
  }

  private show(surface: Surface, sessionId: string): void {
    surface.subscription?.dispose()
    surface.sessionId = sessionId
    surface.subscription = this.manager.subscribe(sessionId, (event) =>
      this.post(surface, { type: 'session', sessionId, event })
    )
    void this.manager.warm(sessionId)
    void this.postProvider(surface)
    this.postLanes(surface)
  }

  private async createFor(surface: Surface): Promise<string> {
    await this.startIn(surface, DEFAULT_PROVIDER)
    if (!surface.sessionId) throw new Error('Could not start a chat.')
    return surface.sessionId
  }

  private async postProvider(surface: Surface): Promise<void> {
    const provider = this.providers.get(this.providerOf(surface.sessionId))
    if (provider) this.post(surface, { type: 'provider', provider: await this.info(provider) })
  }

  /** The chooser lists every provider; sent on ready and after a sign-in. */
  private async postProviders(target?: Surface): Promise<void> {
    const providers = await Promise.all([...this.providers.values()].map((provider) => this.info(provider)))
    if (target) this.post(target, { type: 'providers', providers })
    else this.broadcast({ type: 'providers', providers })
  }

  private async info(provider: ProviderDefinition): Promise<ProviderInfo> {
    const state = this.states.get(provider.id) ?? (await this.probe(provider))
    return {
      id: provider.id,
      label: provider.label,
      installUrl: provider.cli.installUrl,
      capabilities: [...provider.capabilities],
      modes: provider.modes,
      state
    }
  }

  private async probe(provider: ProviderDefinition): Promise<ProviderState> {
    const state = await provider.probe(await this.env())
    this.states.set(provider.id, state)
    return state
  }

  /** Runs the provider's login inside AgentDeck when it can; otherwise in a terminal. */
  private async signIn(surface: Surface, providerId?: string): Promise<void> {
    const provider = this.providers.get(providerId ?? this.providerOf(surface.sessionId))
    if (!provider) return
    if (!provider.startSignIn) return this.signInInTerminal(surface, provider.id)
    this.signIns.get(provider.id)?.flow?.cancel()
    this.setSignIn(provider.id, { step: 'starting' })
    try {
      const flow = await provider.startSignIn(await this.env(), (event) => {
        if (event.kind === 'link') {
          void vscode.env.openExternal(vscode.Uri.parse(event.url))
          this.setSignIn(provider.id, { step: 'link', url: event.url, code: event.code })
        } else if (event.kind === 'failed') {
          this.setSignIn(provider.id, { step: 'failed', message: event.message })
        } else {
          this.setSignIn(provider.id, null)
          this.states.delete(provider.id)
          void this.postProviders()
          for (const target of this.surfaces()) if (this.providerOf(target.sessionId) === provider.id) void this.postProvider(target)
        }
      })
      const current = this.signIns.get(provider.id)
      if (current) current.flow = flow
    } catch (error) {
      this.setSignIn(provider.id, { step: 'failed', message: error instanceof Error ? error.message : String(error) })
    }
  }

  private setSignIn(providerId: string, progress: SignInProgress | null): void {
    if (progress) this.signIns.set(providerId, { flow: this.signIns.get(providerId)?.flow, progress })
    else this.signIns.delete(providerId)
    this.broadcast({ type: 'signInProgress', providerId, progress })
  }

  private surfaces(): Surface[] {
    return [...[...this.panels.values()].map(({ surface }) => surface), ...this.blankPanels, ...(this.sidebar ? [this.sidebar] : [])]
  }

  /** Runs the provider's own login in a terminal, then re-checks once the terminal closes. */
  private async signInInTerminal(surface: Surface, providerId?: string): Promise<void> {
    const provider = this.providers.get(providerId ?? this.providerOf(surface.sessionId))
    if (!provider) return
    const terminal = vscode.window.createTerminal({ name: `${provider.label} sign-in` })
    terminal.show()
    terminal.sendText(provider.signInCommand(await this.env()))
    const closed = vscode.window.onDidCloseTerminal((closedTerminal) => {
      if (closedTerminal !== terminal) return
      closed.dispose()
      this.states.delete(provider.id)
      void this.postProviders()
      if (surface.sessionId) void this.postProvider(surface)
    })
  }

  /** A toast when a chat that is not on screen needs approval. */
  private async attend({ sessionId, reason }: Attention): Promise<void> {
    if (reason !== 'needs-input' || this.visible(sessionId)) return
    const record = this.manager.list().find((entry) => entry.record.id === sessionId)?.record
    if (!record) return
    const label = this.providers.get(record.providerId)?.label ?? record.providerId
    const choice = await vscode.window.showInformationMessage(`${label} needs your input — ${record.title}`, 'Review')
    if (choice !== 'Review') return
    if (this.panels.has(sessionId) || this.sidebar?.sessionId !== sessionId) this.openPanel(sessionId)
    else await vscode.commands.executeCommand(`${SIDEBAR_VIEW}.focus`)
  }

  private visible(sessionId: string): boolean {
    if (this.panels.get(sessionId)?.panel.visible) return true
    return this.sidebar?.sessionId === sessionId && this.sidebarView?.visible === true
  }

  /** Sends the user to where the MCP server's sign-in happens; the token stays with the provider. */
  private async mcpSignIn(surface: Surface, server: string, scope: string | undefined): Promise<void> {
    const provider = this.providers.get(this.providerOf(surface.sessionId))
    const fromSession = surface.sessionId ? await this.manager.mcpSignIn(surface.sessionId, server) : undefined
    const target = fromSession ?? provider?.mcpSignIn?.(server, scope)
    if (!target) return
    if (target.kind === 'url') {
      await vscode.env.openExternal(vscode.Uri.parse(target.url))
      return
    }
    const terminal = vscode.window.createTerminal({ name: `${server} sign-in` })
    terminal.show()
    terminal.sendText(target.command)
    void vscode.window.showInformationMessage(target.hint)
  }

  /** The sidebar's session switcher lists recent sessions. */
  private postSessions(surface = this.sidebar): void {
    if (!surface || surface.kind !== 'view') return
    const sessions = this.manager
      .list()
      .slice(0, 20)
      .map(({ record, status }) => ({
        id: record.id,
        title: record.title,
        providerId: record.providerId,
        status,
        updatedAt: record.updatedAt,
        inTab: this.panels.has(record.id),
        ...(record.laneId ? { laneId: record.laneId } : {})
      }))
    this.post(surface, { type: 'sessions', sessions })
  }

  /** Every surface gets the lane list and the lane its own chat is on. */
  private postLanes(only?: Surface): void {
    if (!this.lanes) return
    const lanes = this.lanes.list()
    for (const surface of only ? [only] : this.surfaces()) {
      this.post(surface, { type: 'lanes', lanes })
      if (!surface.sessionId) continue
      const laneId = this.manager.list().find(({ record }) => record.id === surface.sessionId)?.record.laneId
      this.post(surface, { type: 'lane', sessionId: surface.sessionId, ...(laneId ? { laneId } : {}) })
    }
  }

  private refreshTitles(): void {
    for (const [sessionId, { panel, surface }] of this.panels) {
      const title = this.title(sessionId)
      if (panel.title !== title) panel.title = title
      this.post(surface, { type: 'title', sessionId, title })
    }
    const sidebarSession = this.sidebar?.sessionId
    if (this.sidebar && sidebarSession) {
      this.post(this.sidebar, { type: 'title', sessionId: sidebarSession, title: this.title(sidebarSession) })
    }
  }

  private broadcast(message: HostMessage): void {
    for (const { surface } of this.panels.values()) this.post(surface, message)
    for (const surface of this.blankPanels) this.post(surface, message)
    if (this.sidebar) this.post(this.sidebar, message)
  }

  private post(surface: Surface, message: HostMessage): void {
    void surface.webview.postMessage(message)
  }

  private sidebarSession(): string | undefined {
    const id = this.context.workspaceState.get<string>(SIDEBAR_SESSION_KEY)
    return id && this.exists(id) ? id : undefined
  }

  private exists(sessionId: string): boolean {
    return this.manager.list().some(({ record }) => record.id === sessionId)
  }

  private providerOf(sessionId: string | undefined): string {
    if (!sessionId) return DEFAULT_PROVIDER
    return this.manager.list().find(({ record }) => record.id === sessionId)?.record.providerId ?? DEFAULT_PROVIDER
  }

  private title(sessionId: string): string {
    return this.manager.list().find(({ record }) => record.id === sessionId)?.record.title ?? 'AgentDeck'
  }

  private assets(): vscode.Uri {
    return vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'webview')
  }

  private html(webview: vscode.Webview, kind: SurfaceKind): string {
    const nonce = randomBytes(16).toString('base64')
    const asset = (name: string) => webview.asWebviewUri(vscode.Uri.joinPath(this.assets(), name))
    // Scripts run by nonce; the entry module imports its code-split chunks from the webview origin.
    // Styles allow inline because React, Radix, and Shiki set style attributes.
    const csp = [
      "default-src 'none'",
      `img-src ${webview.cspSource} data:`,
      `font-src ${webview.cspSource}`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `script-src 'nonce-${nonce}' ${webview.cspSource}`
    ].join('; ')
    return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="${asset('codicon.css')}">
<link rel="stylesheet" href="${asset('webview.css')}">
</head>
<body data-surface="${kind}">
<div id="root"></div>
<script type="module" nonce="${nonce}" src="${asset('main.js')}"></script>
</body>
</html>`
  }
}
