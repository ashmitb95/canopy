import * as vscode from 'vscode'
import { githubIssue, githubIssues, type Issue, type IssueRef, linearIssue, linearIssues } from '../integrations/issues'
import type { HostMessage, NewLaneData, WebviewMessage } from './protocol'

type NewLaneDeps = {
  html: (webview: vscode.Webview) => string
  roots: () => vscode.Uri[]
  repos: () => string[]
  /** Where `gh` runs: the first repo. */
  githubCwd: () => string | undefined
  linearKey: () => Promise<string | undefined>
  agents: () => Promise<NewLaneData['agents']>
  roster: () => NewLaneData['roster']
  create: (options: { name: string; repos: string[]; lead: string; issue?: Issue }) => Promise<void>
}

/** The New Worktree form in an editor tab: an issue to start from, the branch, and who leads. */
export class NewLaneView implements vscode.Disposable {
  private panel: vscode.WebviewPanel | undefined

  constructor(private readonly deps: NewLaneDeps) {}

  open(): void {
    if (this.panel) return this.panel.reveal()
    const panel = vscode.window.createWebviewPanel('agentdeck.newLane', 'New Worktree', vscode.ViewColumn.Active, { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: this.deps.roots() })
    panel.webview.html = this.deps.html(panel.webview)
    panel.webview.onDidReceiveMessage((message: WebviewMessage) =>
      this.handle(message).catch((error: unknown) => this.post({ type: 'newLaneError', message: error instanceof Error ? error.message : String(error) }))
    )
    panel.onDidDispose(() => {
      this.panel = undefined
    })
    this.panel = panel
  }

  dispose(): void {
    this.panel?.dispose()
  }

  private post(message: HostMessage): void {
    void this.panel?.webview.postMessage(message)
  }

  /** The form appears at once; issues fill in as each tracker answers. */
  private async data(): Promise<NewLaneData> {
    return { repos: this.deps.repos(), agents: await this.deps.agents(), roster: this.deps.roster(), issues: [], notes: [] }
  }

  private async issues(): Promise<{ issues: IssueRef[]; notes: string[] }> {
    const cwd = this.deps.githubCwd()
    const key = await this.deps.linearKey()
    const notes: string[] = []
    const lists = await Promise.all([
      cwd ? githubIssues(cwd).catch(() => (notes.push('GitHub issues need the gh CLI, signed in.'), [])) : [],
      key ? linearIssues(key).catch((error: Error) => (notes.push(`Linear: ${error.message}`), [])) : (notes.push('Connect Linear in Setup to list its issues.'), [])
    ])
    return { issues: lists.flat(), notes }
  }

  private async fetch(ref: Pick<IssueRef, 'source' | 'id'>): Promise<Issue> {
    if (ref.source === 'github') {
      const cwd = this.deps.githubCwd()
      if (!cwd) throw new Error('Open a folder with a GitHub repo first.')
      return githubIssue(cwd, ref.id)
    }
    const key = await this.deps.linearKey()
    if (!key) throw new Error('Connect Linear in Setup first.')
    return linearIssue(ref.id, key)
  }

  private async handle(message: WebviewMessage): Promise<void> {
    switch (message.type) {
      case 'ready': {
        this.post({ type: 'newLane', data: await this.data() })
        const { issues, notes } = await this.issues()
        this.post({ type: 'newLaneIssues', issues, notes })
        return
      }
      case 'newLaneFindIssue': {
        const ref = message.ref.trim()
        // ENG-214 or a linear.app link is Linear; a number or a GitHub link is GitHub.
        const linear = /([A-Z][A-Z0-9]+-\d+)/.exec(ref)?.[1]
        const issue = await this.fetch(linear && !/github\.com/.test(ref) ? { source: 'linear', id: linear } : { source: 'github', id: ref })
        this.post({ type: 'newLaneIssues', issues: [{ source: issue.source, id: issue.id, title: issue.title, url: issue.url }], notes: [], pick: issue.id })
        return
      }
      case 'newLaneCreate': {
        const issue = message.issue ? await this.fetch(message.issue) : undefined
        await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `Creating ${message.name}…` }, () =>
          this.deps.create({ name: message.name, repos: message.repos, lead: message.lead, ...(issue ? { issue } : {}) })
        )
        this.panel?.dispose()
        return
      }
      case 'openSetup':
        await vscode.commands.executeCommand('agentdeck.openSetup')
        return
      default:
        return
    }
  }
}
