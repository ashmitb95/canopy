import { randomBytes } from 'node:crypto'
import * as vscode from 'vscode'
import type { Disposable } from '../core/emitter'
import type { PromptPart, ProviderDefinition, ProviderState } from '../core/types'
import type { Env } from '../env'
import type { SessionManager } from '../sessions/manager'
import type { DiffDocuments } from './diff-documents'
import type { EditorContextTracker } from './editor-context'
import type { HostMessage, ProviderInfo, WebviewMessage } from './protocol'

export const PANEL_TYPE = 'agentdeck.chatPanel'
export const SIDEBAR_VIEW = 'agentdeck.chat'
const SIDEBAR_SESSION_KEY = 'agentdeck.sidebarSession'
const DEFAULT_PROVIDER = 'claude'

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
  private readonly states = new Map<string, ProviderState>()
  private readonly subscriptions: { dispose(): void }[] = []

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly manager: SessionManager,
    private readonly providers: ReadonlyMap<string, ProviderDefinition>,
    private readonly env: () => Promise<Env>,
    private readonly editor: EditorContextTracker,
    private readonly diffs: DiffDocuments
  ) {
    this.subscriptions.push(
      manager.onDidChange(() => {
        this.refreshTitles()
        this.postSessions()
      }),
      editor.onDidChange((editorContext) => this.broadcast({ type: 'editorContext', context: editorContext }))
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
      localResourceRoots: [this.assets()]
    })
    this.attachPanel(panel)
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
      localResourceRoots: [this.assets()]
    })
    this.attachPanel(panel, sessionId)
  }

  async showInSidebar(sessionId: string): Promise<void> {
    await this.context.workspaceState.update(SIDEBAR_SESSION_KEY, sessionId)
    await vscode.commands.executeCommand(`${SIDEBAR_VIEW}.focus`)
    if (this.sidebar) this.show(this.sidebar, sessionId)
  }

  openSidebarInEditor(): void {
    if (this.sidebar?.sessionId) this.openPanel(this.sidebar.sessionId)
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    view.webview.options = { enableScripts: true, localResourceRoots: [this.assets()] }
    view.webview.html = this.html(view.webview, 'view')
    const surface = this.surface(view.webview, 'view', this.sidebarSession())
    this.sidebar = surface
    view.onDidDispose(() => {
      this.release(surface)
      if (this.sidebar === surface) this.sidebar = undefined
    })
  }

  async deserializeWebviewPanel(panel: vscode.WebviewPanel, state: { sessionId?: string } | undefined): Promise<void> {
    if (!state?.sessionId || !this.exists(state.sessionId)) return panel.dispose()
    this.attachPanel(panel, state.sessionId)
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose()
    for (const { surface } of this.panels.values()) this.release(surface)
    for (const surface of this.blankPanels) this.release(surface)
    if (this.sidebar) this.release(this.sidebar)
  }

  private attachPanel(panel: vscode.WebviewPanel, sessionId?: string): void {
    panel.webview.options = { enableScripts: true, localResourceRoots: [this.assets()] }
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

  private async handle(surface: Surface, message: WebviewMessage): Promise<void> {
    const sessionId = surface.sessionId
    switch (message.type) {
      case 'ready':
        this.post(surface, { type: 'editorContext', context: this.editor.current() })
        this.postSessions(surface)
        await this.postProviders(surface)
        if (sessionId) this.show(surface, sessionId)
        else this.post(surface, { type: 'empty' })
        return
      case 'prompt': {
        const target = sessionId ?? (await this.createFor(surface))
        const parts: PromptPart[] = [{ type: 'text', text: message.text }]
        const file = message.includeContext ? this.editor.part() : null
        if (file) parts.push(file)
        return this.manager.prompt(target, parts)
      }
      case 'cancel':
        if (sessionId) await this.manager.cancel(sessionId)
        return
      case 'answer':
        if (sessionId) this.manager.answer(sessionId, message.itemId, message.optionId)
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

  /** Runs the provider's own login in a terminal, then re-checks once the terminal closes. */
  private async signIn(surface: Surface, providerId?: string): Promise<void> {
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
        updatedAt: record.updatedAt
      }))
    this.post(surface, { type: 'sessions', sessions })
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
