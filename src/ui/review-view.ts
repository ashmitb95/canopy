import * as vscode from 'vscode'
import { diffFiles } from '../group/diff-files'
import type { GroupChat, GroupChats } from '../group/chat'
import { createPullRequest } from '../integrations/issues'
import type { Lane } from '../lanes/lanes'
import type { RepoState } from '../lanes/state'
import type { HostMessage, ReviewData, WebviewMessage } from './protocol'

/** Long diffs are cut here; the full change opens in VS Code's diff view. */
const MAX_LINES = 400

type ReviewDeps = {
  html: (webview: vscode.Webview) => string
  roots: () => vscode.Uri[]
  chats: GroupChats
  lanes: () => Lane[]
  repos: () => RepoState[]
  switchLane: (lane: string) => Promise<void>
}

/** One editor tab per group chat, to review what each agent did before shipping it. */
export const REVIEW_PANEL = 'canopy.review'

export class ReviewView implements vscode.WebviewPanelSerializer, vscode.Disposable {
  private readonly panels = new Map<string, { panel: vscode.WebviewPanel; listener: { dispose(): void } }>()

  constructor(private readonly deps: ReviewDeps) {}

  open(groupId: string): void {
    const open = this.panels.get(groupId)
    if (open) return open.panel.reveal()
    const chat = this.deps.chats.get(groupId)
    if (!chat) return
    this.adopt(vscode.window.createWebviewPanel(REVIEW_PANEL, `Review: ${chat.record.title}`, vscode.ViewColumn.Active, { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: this.deps.roots() }), chat)
  }

  /** A review tab VS Code restored after a reload; the webview saved which chat it reviews. */
  async deserializeWebviewPanel(panel: vscode.WebviewPanel, state: { groupId?: string } | undefined): Promise<void> {
    const chat = state?.groupId ? this.deps.chats.get(state.groupId) : undefined
    if (!chat || this.panels.has(chat.record.id)) return panel.dispose()
    panel.title = `Review: ${chat.record.title}`
    this.adopt(panel, chat)
  }

  private adopt(panel: vscode.WebviewPanel, chat: GroupChat): void {
    const groupId = chat.record.id
    panel.webview.options = { enableScripts: true, localResourceRoots: this.deps.roots() }
    panel.webview.html = this.deps.html(panel.webview)
    panel.webview.onDidReceiveMessage((message: WebviewMessage) =>
      this.handle(chat, message).catch((error: unknown) => vscode.window.showErrorMessage(`Canopy: ${error instanceof Error ? error.message : String(error)}`))
    )
    const listener = chat.onEvent((event) => event.type === 'state' && this.post(chat))
    panel.onDidDispose(() => {
      listener.dispose()
      this.panels.delete(groupId)
    })
    this.panels.set(groupId, { panel, listener })
  }

  dispose(): void {
    for (const { panel } of this.panels.values()) panel.dispose()
  }

  private lane(chat: GroupChat): Lane | undefined {
    return chat.record.laneId ? this.deps.lanes().find((lane) => lane.name === chat.record.laneId) : undefined
  }

  private data(chat: GroupChat): ReviewData {
    const diffs = new Map(chat.review().map(({ delegation, diff }) => [delegation.id, diff]))
    const lane = this.lane(chat)
    return {
      groupId: chat.record.id,
      title: chat.record.title,
      ...(chat.record.laneId ? { laneId: chat.record.laneId } : {}),
      inPrimary: lane?.repos.some((repo) => repo.location === 'primary') ?? false,
      delegations: chat.record.delegations.map((delegation) => ({
        id: delegation.id,
        agent: delegation.agent,
        ...(delegation.role ? { role: delegation.role } : {}),
        task: delegation.task,
        status: delegation.status,
        ...(delegation.report ? { report: delegation.report } : {}),
        ...(delegation.facts?.verify ? { verify: { command: delegation.facts.verify.command, ok: delegation.facts.verify.ok } } : {}),
        violations: delegation.facts?.violations ?? [],
        commands: delegation.facts?.commands.length ?? 0,
        failedCommands: delegation.facts?.commands.filter((command) => command.failed).length ?? 0,
        undone: Boolean(delegation.undone),
        handoff: Boolean(delegation.handoff),
        files: diffFiles(diffs.get(delegation.id) ?? '').map((file) => ({ ...file, lines: file.lines.slice(0, MAX_LINES) }))
      }))
    }
  }

  private post(chat: GroupChat): void {
    void this.panels.get(chat.record.id)?.panel.webview.postMessage({ type: 'review', review: this.data(chat) } satisfies HostMessage)
  }

  private async handle(chat: GroupChat, message: WebviewMessage): Promise<void> {
    switch (message.type) {
      case 'ready':
        return this.post(chat)
      case 'undoDelegation':
        void vscode.window.showInformationMessage(chat.undoDelegation(message.id))
        return this.post(chat)
      case 'viewHandoff': {
        const handoff = chat.record.delegations.find((delegation) => delegation.id === message.id)?.handoff
        if (handoff) await vscode.window.showTextDocument(vscode.Uri.file(handoff), { preview: true })
        return
      }
      case 'openLaneDiff':
        if (chat.record.laneId) await vscode.commands.executeCommand('canopy.reviewLane', chat.record.laneId)
        return
      case 'switchLane':
        if (chat.record.laneId) await this.deps.switchLane(chat.record.laneId)
        return
      case 'createPullRequest':
        return this.pullRequest(chat)
      default:
        return
    }
  }

  /** Pushes the lane's branch in each repo it touches and opens a pull request there, after the user confirms. */
  private async pullRequest(chat: GroupChat): Promise<void> {
    const lane = this.lane(chat)
    if (!lane || lane.repos.length === 0) return void vscode.window.showWarningMessage('This chat has no lane checked out to open a pull request from.')
    const names = lane.repos.map((repo) => repo.repo).join(', ')
    const choice = await vscode.window.showWarningMessage(`Push ${lane.name} to origin and open a pull request in ${names}?`, { modal: true, detail: 'Only committed work is pushed. Canopy never force-pushes.' }, 'Open pull request')
    if (choice !== 'Open pull request') return
    const body = [
      '## Who did what',
      '',
      ...chat.record.delegations.filter((delegation) => !delegation.undone).map((delegation) => `- **${delegation.agent}**${delegation.role ? ` (${delegation.role})` : ''}: ${(delegation.report ?? delegation.task).split('\n')[0]}`)
    ].join('\n')
    const urls: string[] = []
    for (const laneRepo of lane.repos) {
      const base = this.deps.repos().find((repo) => repo.name === laneRepo.repo)?.base
      if (!base) continue
      urls.push(await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `Opening a pull request in ${laneRepo.repo}…` }, () => createPullRequest(laneRepo.path, { branch: lane.name, base, title: chat.record.title, body })))
    }
    for (const url of urls) {
      const open = await vscode.window.showInformationMessage(`Pull request opened: ${url}`, 'Open')
      if (open) await vscode.env.openExternal(vscode.Uri.parse(url))
    }
  }
}
