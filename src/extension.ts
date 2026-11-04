import { homedir } from 'node:os'
import { join, relative } from 'node:path'
import * as vscode from 'vscode'
import { captureEnv, type Env } from './env'
import { setLog } from './log'
import { laneDescription } from './lanes/lanes'
import { handoffPrompt, readTasks } from './lanes/tasks'
import { customAgent } from './providers/acp/agents'
import { buildProviders } from './providers/registry'
import type { SessionManager } from './sessions/manager'
import { type Core, createCore } from './group/host'
import { seedLane } from './integrations/issues'
import { attachFile } from './ui/attachments'
import { ChatSurfaces, type LaneSource, PANEL_TYPE, SIDEBAR_VIEW } from './ui/chat-surfaces'
import { configFiles } from './ui/config-files'
import { DIFF_SCHEME, DiffDocuments } from './ui/diff-documents'
import { EditorContextTracker } from './ui/editor-context'
import { GIT_SCHEME, LaneChanges } from './ui/lane-changes'
import { Notifier } from './ui/notifier'
import type { LaneNode, SessionNode } from './ui/sessions-tree'
import { NewLaneView } from './ui/new-lane-view'
import { ReviewView } from './ui/review-view'
import { SetupView } from './ui/setup-view'
import { SIDE_VIEW, SideView } from './ui/side-view'
import { SessionsStatusBar } from './ui/status-bar'
import { KeepAwake } from './ui/keep-awake'
import { Unread } from './ui/unread'

let manager: SessionManager | undefined
let core: Core | undefined

/** Where the Linear key lives: VS Code's SecretStorage, sent only to Linear. */
const LINEAR_SECRET = 'canopy.linearKey'

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const output = vscode.window.createOutputChannel('Canopy')
  context.subscriptions.push(output)
  setLog((line, reveal) => {
    output.appendLine(`${new Date().toTimeString().slice(0, 8)} ${line}`)
    if (reveal) output.show(true)
  })
  const custom = vscode.workspace.getConfiguration('canopy').get<Record<string, unknown>[]>('customAgents', [])
  const providers = buildProviders(custom.flatMap((entry) => customAgent(entry) ?? []))
  let env: Promise<Env> | undefined
  // claude-notifier's hooks read this; Canopy notifies for the CLIs it runs itself.
  const getEnv = () => (env ??= captureEnv().then((captured) => ({ ...captured, CLAUDE_NOTIFIER_DISABLE: '1' })))
  const storage = (context.storageUri ?? context.globalStorageUri).fsPath
  const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
  // The same core the terminal driver hosts. Without a folder it works in Canopy's storage, so the home folder is never scanned.
  core = await createCore({ root: root ?? storage, storage, memento: context.workspaceState, env: getEnv, providers })
  manager = core.manager
  const sessionManager = core.manager
  const tracker = root ? core.tracker : undefined
  const memory = root ? core.memory : undefined
  const lanes = root ? core.lanes : undefined
  const editor = new EditorContextTracker()
  const diffs = new DiffDocuments(sessionManager)
  const unread = new Unread(context.workspaceState)
  let side: SideView
  const laneSource: LaneSource | undefined = tracker
    ? { list: () => side.allLanes().map((lane) => ({ name: lane.name, where: laneDescription(lane) })), onDidChange: tracker.onDidChange }
    : undefined
  const laneChanges = new LaneChanges()
  const surfaces = new ChatSurfaces(context, sessionManager, providers, getEnv, editor, diffs, unread, laneSource, core.chats)
  side = new SideView((webview, kind) => surfaces.html(webview, kind), () => surfaces.roots(), sessionManager, core.chats, unread, tracker, lanes, memory)

  const setup = new SetupView((webview) => surfaces.html(webview, 'setup'), () => surfaces.roots(), () => surfaces.providerInfos(), context.secrets, LINEAR_SECRET, tracker, root ?? storage)

  const review = new ReviewView({
    html: (webview) => surfaces.html(webview, 'review'),
    roots: () => surfaces.roots(),
    chats: core.chats,
    lanes: () => side.allLanes(),
    repos: () => tracker?.repos ?? [],
    switchLane: (lane) => side.switchLane(lane)
  })

  // A lane switch that stopped partway (a crash, a closed window) leaves stashes and branches mid-move; offer to put them back.
  void lanes?.unfinishedMoves().then(async (moves) => {
    if (moves.length === 0) return
    const what = moves.map((move) => `${move.lane} in ${move.repo}`).join(', ')
    const choice = await vscode.window.showWarningMessage(`A lane switch was interrupted: ${what}.`, 'Undo it', 'Leave it')
    if (choice === 'Undo it') await runLane('Undoing the interrupted switch…', async () => void vscode.window.showInformationMessage((await lanes.undoUnfinishedMoves()).join(' · ')))
  })

  context.subscriptions.push(surfaces.useLanes({ cards: () => side.laneCards(), handle: (message) => side.handleLane(message), onChange: (listener) => side.onLanesChanged(listener) }))

  // Every chat started from a provider is a group chat it leads, so the roster and delegation always apply.
  surfaces.startGroup = async (lead, text) => {
    const chat = await newGroup(lead ? { lead } : {})
    if (chat && text) await chat.send(text)
  }

  /** A group chat with the roster from settings; the lead can be overridden. */
  const newGroup = async (options: { lead?: string; laneId?: string; title?: string }) => {
    const config = vscode.workspace.getConfiguration('canopy.roster')
    const lead = options.lead ?? config.get<string>('lead', 'claude')
    const roster = { plan: lead, ...Object.fromEntries((['research', 'implement', 'review'] as const).flatMap((role) => {
      const agent = config.get<string>(role, '')
      return agent ? [[role, agent]] : []
    })) }
    const verify = config.get<string>('verify')
    const chat = core?.chats.create({ lead, roster, mode: 'accept-edits', enforce: config.get<boolean>('enforce', true), questionsTo: config.get<'lead' | 'user'>('questionsTo', 'lead'), ...(verify ? { verify } : {}), ...(options.laneId ? { laneId: options.laneId } : {}), ...(options.title ? { title: options.title } : {}) })
    if (chat) await surfaces.showGroupInSidebar(chat.record.id)
    return chat
  }

  const newLane = new NewLaneView({
    html: (webview) => surfaces.html(webview, 'new-lane'),
    roots: () => surfaces.roots(),
    repos: () => tracker?.repos.map((repo) => repo.name) ?? [],
    githubCwd: () => tracker?.repos[0]?.path,
    linearKey: async () => context.secrets.get(LINEAR_SECRET),
    agents: async () => (await surfaces.providerInfos()).map((agent) => ({ id: agent.id, label: agent.label, ready: agent.state.status === 'signed-in' })),
    roster: () => {
      const config = vscode.workspace.getConfiguration('canopy.roster')
      return { lead: config.get('lead', 'claude'), research: config.get('research', ''), implement: config.get('implement', ''), review: config.get('review', '') }
    },
    create: async ({ name, repos, lead, issue }) => {
      if (!lanes) throw new Error('Open a folder to use lanes.')
      if (issue && memory) seedLane(memory, name, issue)
      await lanes.newLane(name, repos, { worktrees: true, ...(issue ? { goal: `${issue.title} (${issue.id})` } : {}) })
      await newGroup({ lead, laneId: name, title: issue?.title ?? name })
    }
  })

  void surfaces.markInstalled()
  const notifier = new Notifier(
    sessionManager,
    new Map([...providers].map(([id, provider]) => [id, provider.label])),
    (id) => surfaces.visible(id)
  )
  context.subscriptions.push(
    editor,
    surfaces,
    new KeepAwake(sessionManager),
    notifier,
    vscode.commands.registerCommand('canopy.testNotification', async () => {
      const event = await vscode.window.showQuickPick(['finished', 'approval', 'question', 'failed'], { placeHolder: 'Which notification?' })
      if (event) notifier.test(event as 'finished' | 'approval' | 'question' | 'failed')
    }),
    vscode.window.registerWebviewViewProvider(SIDEBAR_VIEW, surfaces, { webviewOptions: { retainContextWhenHidden: true } }),
    vscode.window.registerWebviewPanelSerializer(PANEL_TYPE, surfaces),
    vscode.commands.registerCommand('canopy.newChat', () => surfaces.newChat('panel')),
    vscode.commands.registerCommand('canopy.sidebar.newChat', () => surfaces.newChat('view')),
    vscode.commands.registerCommand('canopy.newChat.other', () => surfaces.newChat('view')),
    ...[...providers.keys()].map((id) => vscode.commands.registerCommand(`canopy.newChat.${id}`, () => surfaces.newChat('view', id))),
    vscode.commands.registerCommand('canopy.newGroupChat', (options?: { laneId?: string; title?: string }) => newGroup(options ?? {})),
    vscode.commands.registerCommand('canopy.setLinearKey', async () => {
      const key = await vscode.window.showInputBox({ prompt: 'Linear personal API key (Settings → Security & access in Linear)', password: true, ignoreFocusOut: true })
      if (key?.trim()) await context.secrets.store(LINEAR_SECRET, key.trim())
    }),
    vscode.commands.registerCommand('canopy.clearLinearKey', () => context.secrets.delete(LINEAR_SECRET)),
    vscode.commands.registerCommand('canopy.openInEditor', () => surfaces.openSidebarInEditor()),
    vscode.commands.registerCommand('canopy.manageProviders', () => surfaces.openProviders()),
    vscode.workspace.registerTextDocumentContentProvider(DIFF_SCHEME, diffs),
    vscode.workspace.registerTextDocumentContentProvider(GIT_SCHEME, laneChanges),
    vscode.commands.registerCommand('canopy.reviewLane', async (target: LaneNode | string) => {
      const name = typeof target === 'string' ? target : target.lane.name
      const lane = side.allLanes().find((candidate) => candidate.name === name)
      if (lane && tracker) await laneChanges.open(lane, tracker.repos)
    }),
    side,
    vscode.window.registerWebviewViewProvider(SIDE_VIEW, side, { webviewOptions: { retainContextWhenHidden: true } }),
    vscode.commands.registerCommand('canopy.openGroup', (groupId: string) => surfaces.showGroupInSidebar(groupId)),
    vscode.commands.registerCommand('canopy.openLanes', () => side.openLanes()),
    vscode.commands.registerCommand('canopy.openSetup', () => setup.open()),
    vscode.commands.registerCommand('canopy.reviewGroup', (groupId: string) => review.open(groupId)),
    review,
    setup,
    new SessionsStatusBar(sessionManager),
    vscode.commands.registerCommand('canopy.openSession', (node: SessionNode) => surfaces.openPanel(node.id)),
    vscode.commands.registerCommand('canopy.openSessionInSidebar', (node: SessionNode) => surfaces.showInSidebar(node.id)),
    vscode.commands.registerCommand('canopy.renameSession', async (node: { id: string; title: string }) => {
      const title = await vscode.window.showInputBox({ prompt: 'Session name', value: node.title })
      if (title?.trim()) await sessionManager.rename(node.id, title.trim())
    }),
    vscode.commands.registerCommand('canopy.forkSession', async (target?: SessionNode | string) => {
      const id = typeof target === 'string' ? target : (target?.id ?? surfaces.activeSessionId())
      if (!id) return
      try {
        const fork = await sessionManager.fork(id)
        surfaces.openPanel(fork.id)
      } catch (error) {
        void vscode.window.showErrorMessage((error as Error).message)
      }
    }),
    vscode.commands.registerCommand('canopy.addToChat', async (uri?: vscode.Uri, selected?: vscode.Uri[]) => {
      const uris = selected?.length ? selected : uri ? [uri] : vscode.window.activeTextEditor ? [vscode.window.activeTextEditor.document.uri] : []
      const files = uris.filter((candidate) => candidate.scheme === 'file')
      if (files.length === 0) return
      await surfaces.insertAttachments(files.map((file) => attachFile(join(storage, 'attachments'), file.fsPath, vscode.workspace.asRelativePath(file))))
    }),
    vscode.commands.registerCommand('canopy.openProviderConfig', async () => {
      const files = configFiles(homedir(), root)
      if (files.length === 0) return void vscode.window.showInformationMessage('No provider config files found.')
      const choice = await vscode.window.showQuickPick(
        files.map((file) => ({ label: file.label, description: file.path.replace(homedir(), '~'), path: file.path })),
        { placeHolder: 'Open which config?' }
      )
      if (choice) await vscode.window.showTextDocument(vscode.Uri.file(choice.path))
    }),
    vscode.commands.registerCommand('canopy.moveSessionToLane', async (node: SessionNode) => {
      const none = { label: '$(circle-slash) No branch', lane: undefined }
      const choices = [
        ...side.allLanes().map((lane) => ({ label: `$(git-branch) ${lane.name}`, description: laneDescription(lane), lane: lane.name })),
        none
      ]
      const choice = await vscode.window.showQuickPick(choices, { placeHolder: `Move “${node.title}” to…` })
      if (choice) await sessionManager.setLane(node.id, choice.lane)
    }),
    vscode.commands.registerCommand('canopy.setLaneGoal', async (node: LaneNode) => {
      if (!memory) return
      const goal = await vscode.window.showInputBox({ prompt: `Goal for ${node.lane.name}`, value: memory.goal(node.lane.name) ?? '' })
      if (goal?.trim()) memory.setGoal(node.lane.name, goal.trim())
    }),
    vscode.commands.registerCommand('canopy.openLanePlan', async (node: LaneNode) => {
      if (!memory) return
      memory.ensure(node.lane.name)
      await vscode.window.showTextDocument(vscode.Uri.file(memory.planPath(node.lane.name)))
    }),
    vscode.commands.registerCommand('canopy.newLane', () => (lanes ? newLane.open() : vscode.window.showInformationMessage('Open a folder to use lanes.'))),
    newLane,
    vscode.commands.registerCommand('canopy.laneIntoPrimary', (node: LaneNode) =>
      lanes ? runLane(`Moving ${node.lane.name} to the primary checkout…`, () => lanes.moveIntoPrimary(node.lane.name)) : undefined
    ),
    vscode.commands.registerCommand('canopy.laneToWorktree', (node: LaneNode) =>
      lanes ? runLane(`Moving ${node.lane.name} to worktrees…`, () => lanes.moveToWorktree(node.lane.name)) : undefined
    ),
    vscode.commands.registerCommand('canopy.handOff', async (target?: SessionNode | string) => {
      const sourceId = typeof target === 'string' ? target : (target?.id ?? surfaces.activeSessionId())
      const source = sessionManager.list().find(({ record }) => record.id === sourceId)?.record
      if (!source) return void vscode.window.showInformationMessage('Open a chat to hand off from.')
      const tasks = readTasks(root ?? '')
      const task = await vscode.window.showQuickPick(
        tasks.map((candidate) => ({
          label: candidate.label,
          description: `${providers.get(candidate.provider)?.label ?? candidate.provider} · ${candidate.mode}`,
          task: candidate
        })),
        { placeHolder: `Hand off “${source.title}” to…` }
      )
      if (!task) return
      if (!providers.has(task.task.provider)) {
        return void vscode.window.showErrorMessage(`No provider “${task.task.provider}”. Check [task.${task.task.id}] in .canopy/config.toml.`)
      }
      const summary = source.laneId && memory ? join(memory.laneDir(source.laneId), 'chats', `${source.id}.md`) : undefined
      const text = await vscode.window.showInputBox({
        prompt: `First prompt for the ${task.task.label} chat (edit before sending)`,
        value: handoffPrompt({
          task: task.task.label,
          from: source.title,
          ...(source.laneId ? { lane: source.laneId } : {}),
          ...(summary && tracker ? { summaryPath: relative(tracker.root, summary) } : {}),
          reply: sessionManager.lastReply(source.id)
        })
      })
      if (!text?.trim()) return
      const next = await sessionManager.create(task.task.provider, task.task.mode)
      if (source.laneId) await sessionManager.setLane(next.id, source.laneId)
      surfaces.openPanel(next.id)
      await sessionManager.prompt(next.id, [{ type: 'text', text: text.trim() }])
    }),
    vscode.commands.registerCommand('canopy.stopSession', (node: SessionNode) => sessionManager.stop(node.id)),
    vscode.commands.registerCommand('canopy.deleteSession', async (node: { id: string; title: string }) => {
      const choice = await vscode.window.showWarningMessage(`Delete “${node.title}”?`, { modal: true }, 'Delete')
      if (choice === 'Delete') await sessionManager.delete(node.id)
    })
  )

  if (tracker) {
    context.subscriptions.push(
      // Saves change dirty counts; refocusing catches work done in a terminal or another app.
      vscode.workspace.onDidSaveTextDocument(() => tracker.schedule()),
      vscode.window.onDidChangeWindowState((state) => state.focused && tracker.schedule())
    )
  }

  // First run: show the providers and how to start, once.
  if (!context.globalState.get('canopy.welcomed') && sessionManager.list().length === 0) {
    void context.globalState.update('canopy.welcomed', true)
    surfaces.openProviders('Welcome to Canopy')
  }
}

export async function deactivate(): Promise<void> {
  await core?.dispose()
}

/** Runs a lane operation with progress; failures (busy chats, stash conflicts) show their message. */
async function runLane(title: string, operation: () => Promise<unknown>): Promise<boolean> {
  try {
    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title }, operation)
    return true
  } catch (error) {
    void vscode.window.showErrorMessage((error as Error).message)
    return false
  }
}
