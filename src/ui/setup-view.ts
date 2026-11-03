import { execFile } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'
import * as vscode from 'vscode'
import { envFilesFor, readConfig, updateConfig } from '../lanes/config'
import type { LaneTracker } from '../lanes/tracker'
import type { HostMessage, ProviderInfo, SetupData, WebviewMessage } from './protocol'

const CONFIG_TEMPLATE = `# AgentDeck workspace settings. Every key is optional.

# Files copied from the primary checkout into a new worktree.
# env_files = [".env*"]

# Whether new lanes start in worktrees.
# worktrees = true

# How many worktree slots each repo may hold.
# max_slots = 4

# A setup command per repo, run in a new worktree.
# [setup]
# api = "pnpm install"
`

/** Whether `gh` is installed and signed in; GitHub issues and pull requests go through it. */
function githubStatus(cwd: string): Promise<SetupData['github']> {
  return new Promise((resolve) => {
    execFile('gh', ['auth', 'status'], { cwd, timeout: 10_000 }, (error) => {
      if (!error) return resolve('signed-in')
      resolve((error as NodeJS.ErrnoException).code === 'ENOENT' ? 'missing' : 'signed-out')
    })
  })
}

/** The setup page in an editor tab: agents, who does what, the workspace, and issue trackers. */
export class SetupView implements vscode.Disposable {
  private panel: vscode.WebviewPanel | undefined
  private readonly subscription: vscode.Disposable

  constructor(
    private readonly html: (webview: vscode.Webview) => string,
    private readonly roots: () => vscode.Uri[],
    private readonly providers: () => Promise<ProviderInfo[]>,
    private readonly secrets: vscode.SecretStorage,
    private readonly linearKey: string,
    private readonly tracker: LaneTracker | undefined,
    private readonly cwd: string
  ) {
    this.subscription = vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration('agentdeck.roster') || event.affectsConfiguration('agentdeck.palette')) void this.refresh()
    })
  }

  open(): void {
    if (this.panel) return this.panel.reveal()
    const panel = vscode.window.createWebviewPanel('agentdeck.setup', 'AgentDeck Setup', vscode.ViewColumn.Active, { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: this.roots() })
    panel.webview.html = this.html(panel.webview)
    panel.webview.onDidReceiveMessage((message: WebviewMessage) =>
      this.handle(message).catch((error: unknown) => vscode.window.showErrorMessage(`AgentDeck: ${error instanceof Error ? error.message : String(error)}`))
    )
    // Agents may have been signed in elsewhere while the page was hidden.
    panel.onDidChangeViewState(() => panel.visible && void this.refresh())
    panel.onDidDispose(() => {
      this.panel = undefined
    })
    this.panel = panel
  }

  dispose(): void {
    this.subscription.dispose()
    this.panel?.dispose()
  }

  private async refresh(): Promise<void> {
    if (this.panel) void this.panel.webview.postMessage({ type: 'setup', setup: await this.data() } satisfies HostMessage)
  }

  private async data(): Promise<SetupData> {
    const roster = vscode.workspace.getConfiguration('agentdeck.roster')
    const [agents, github, linear] = await Promise.all([this.providers(), githubStatus(this.tracker?.repos[0]?.path ?? this.cwd), this.secrets.get(this.linearKey)])
    const config = this.tracker ? readConfig(this.tracker.root) : undefined
    return {
      agents: agents.map((agent) => ({
        id: agent.id,
        label: agent.label,
        status: agent.state.status,
        installUrl: agent.installUrl,
        ...(agent.state.account ? { account: agent.state.account } : {}),
        ...(agent.state.version ? { version: agent.state.version } : {})
      })),
      roster: {
        lead: roster.get<string>('lead', 'claude'),
        research: roster.get<string>('research', ''),
        implement: roster.get<string>('implement', ''),
        review: roster.get<string>('review', ''),
        enforce: roster.get<boolean>('enforce', true),
        verify: roster.get<string>('verify', ''),
        questionsTo: roster.get<'lead' | 'user'>('questionsTo', 'lead')
      },
      ...(config && this.tracker
        ? {
            workspace: {
              name: basename(this.tracker.root),
              maxSlots: config.maxSlots,
              worktrees: config.worktrees,
              envFiles: config.envFiles,
              repos: this.tracker.repos.map((repo) => ({ name: repo.name, ...(repo.base ? { base: repo.base } : {}), ...(config.setup[repo.name] ? { setup: config.setup[repo.name] } : {}), envFiles: envFilesFor(config, repo.name) }))
            }
          }
        : {}),
      github,
      linear: Boolean(linear),
      palette: vscode.workspace.getConfiguration('agentdeck').get<string>('palette', 'paper')
    }
  }

  private async handle(message: WebviewMessage): Promise<void> {
    const roster = vscode.workspace.getConfiguration('agentdeck.roster')
    switch (message.type) {
      case 'ready':
        return this.refresh()
      case 'setRoster':
        return roster.update(message.role, message.value, vscode.ConfigurationTarget.Workspace)
      case 'setEnforce':
        return roster.update('enforce', message.value, vscode.ConfigurationTarget.Workspace)
      case 'setQuestionsTo':
        return roster.update('questionsTo', message.value, vscode.ConfigurationTarget.Global)
      case 'setPalette':
        return vscode.workspace.getConfiguration('agentdeck').update('palette', message.value, vscode.ConfigurationTarget.Global)
      case 'setRepoSetup':
        if (this.tracker) updateConfig(this.tracker.root, { setup: { [message.repo]: message.command } })
        return this.refresh()
      case 'setRepoEnvFiles':
        if (this.tracker) updateConfig(this.tracker.root, { env: { [message.repo]: message.value.split(',').map((file) => file.trim()).filter(Boolean) } })
        return this.refresh()
      case 'installAgent': {
        const agent = (await this.providers()).find((candidate) => candidate.id === message.providerId)
        if (agent) await vscode.env.openExternal(vscode.Uri.parse(agent.installUrl))
        return
      }
      case 'addAgent':
        await vscode.commands.executeCommand('workbench.action.openSettings', 'agentdeck.customAgents')
        return
      case 'finishSetup':
        this.panel?.dispose()
        await vscode.commands.executeCommand('agentdeck.openLanes')
        return
      case 'manageAgents':
        await vscode.commands.executeCommand('agentdeck.manageProviders')
        return
      case 'connectLinear':
        await vscode.commands.executeCommand('agentdeck.setLinearKey')
        return this.refresh()
      case 'disconnectLinear':
        await vscode.commands.executeCommand('agentdeck.clearLinearKey')
        return this.refresh()
      case 'editWorkspaceConfig': {
        if (!this.tracker) return
        const path = join(this.tracker.root, '.agentdeck', 'config.toml')
        if (!existsSync(path)) {
          mkdirSync(dirname(path), { recursive: true })
          writeFileSync(path, CONFIG_TEMPLATE)
        }
        await vscode.window.showTextDocument(vscode.Uri.file(path))
        return
      }
      default:
        return
    }
  }
}
