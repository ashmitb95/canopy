import { homedir } from 'node:os'
import { join } from 'node:path'
import * as vscode from 'vscode'
import { captureEnv, type Env } from './env'
import { laneContext } from './lanes/lane-context'
import { watchHistory, watchTurns } from './lanes/lane-turns'
import { LaneMemory } from './lanes/memory'
import { LaneTracker } from './lanes/tracker'
import { providers } from './providers/registry'
import { SessionManager } from './sessions/manager'
import { SessionStore } from './sessions/store'
import { ChatSurfaces, PANEL_TYPE, SIDEBAR_VIEW } from './ui/chat-surfaces'
import { DIFF_SCHEME, DiffDocuments } from './ui/diff-documents'
import { EditorContextTracker } from './ui/editor-context'
import { type LaneNode, laneDescription, type SessionNode, SessionsTree } from './ui/sessions-tree'
import { SessionsStatusBar } from './ui/status-bar'

let manager: SessionManager | undefined

export function activate(context: vscode.ExtensionContext): void {
  let env: Promise<Env> | undefined
  const getEnv = () => (env ??= captureEnv())
  const storage = (context.storageUri ?? context.globalStorageUri).fsPath
  const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
  // Without a folder there is nothing to track (and the home folder is not scanned).
  const tracker = root ? new LaneTracker(root) : undefined
  const memory = tracker ? new LaneMemory(tracker.root) : undefined
  manager = new SessionManager({
    providers,
    store: new SessionStore(context.workspaceState),
    journalDir: join(storage, 'sessions'),
    cwd: root ?? homedir(),
    env: getEnv,
    decorate: tracker && memory ? laneContext(tracker, memory) : undefined
  })
  const sessionManager = manager
  const editor = new EditorContextTracker()
  const diffs = new DiffDocuments(manager)
  const surfaces = new ChatSurfaces(context, manager, providers, getEnv, editor, diffs)
  const tree = new SessionsTree(sessionManager, new Map([...providers].map(([id, provider]) => [id, provider.label])), tracker)
  context.subscriptions.push(
    editor,
    surfaces,
    vscode.window.registerWebviewViewProvider(SIDEBAR_VIEW, surfaces, { webviewOptions: { retainContextWhenHidden: true } }),
    vscode.window.registerWebviewPanelSerializer(PANEL_TYPE, surfaces),
    vscode.commands.registerCommand('agentdeck.newChat', () => surfaces.newChat('panel')),
    vscode.commands.registerCommand('agentdeck.sidebar.newChat', () => surfaces.newChat('view')),
    vscode.commands.registerCommand('agentdeck.openInEditor', () => surfaces.openSidebarInEditor()),
    vscode.commands.registerCommand('agentdeck.manageProviders', () => surfaces.openProviders()),
    vscode.workspace.registerTextDocumentContentProvider(DIFF_SCHEME, diffs),
    tree,
    new SessionsStatusBar(sessionManager),
    vscode.commands.registerCommand('agentdeck.openSession', (node: SessionNode) => surfaces.openPanel(node.id)),
    vscode.commands.registerCommand('agentdeck.openSessionInSidebar', (node: SessionNode) => surfaces.showInSidebar(node.id)),
    vscode.commands.registerCommand('agentdeck.renameSession', async (node: SessionNode) => {
      const title = await vscode.window.showInputBox({ prompt: 'Session name', value: node.title })
      if (title?.trim()) await sessionManager.rename(node.id, title.trim())
    }),
    vscode.commands.registerCommand('agentdeck.moveSessionToLane', async (node: SessionNode) => {
      const none = { label: '$(circle-slash) No branch', lane: undefined }
      const choices = [
        ...tree.lanes().map((lane) => ({ label: `$(git-branch) ${lane.name}`, description: laneDescription(lane), lane: lane.name })),
        none
      ]
      const choice = await vscode.window.showQuickPick(choices, { placeHolder: `Move “${node.title}” to…` })
      if (choice) await sessionManager.setLane(node.id, choice.lane)
    }),
    vscode.commands.registerCommand('agentdeck.setLaneGoal', async (node: LaneNode) => {
      if (!memory) return
      const goal = await vscode.window.showInputBox({ prompt: `Goal for ${node.lane.name}`, value: memory.goal(node.lane.name) ?? '' })
      if (goal?.trim()) memory.setGoal(node.lane.name, goal.trim())
    }),
    vscode.commands.registerCommand('agentdeck.openLanePlan', async (node: LaneNode) => {
      if (!memory) return
      memory.ensure(node.lane.name)
      await vscode.window.showTextDocument(vscode.Uri.file(memory.planPath(node.lane.name)))
    }),
    vscode.commands.registerCommand('agentdeck.stopSession', (node: SessionNode) => sessionManager.stop(node.id)),
    vscode.commands.registerCommand('agentdeck.deleteSession', async (node: SessionNode) => {
      const choice = await vscode.window.showWarningMessage(`Delete “${node.title}”?`, { modal: true }, 'Delete')
      if (choice === 'Delete') await sessionManager.delete(node.id)
    })
  )

  if (tracker) {
    void tracker.refresh().catch(() => {})
    context.subscriptions.push(
      tracker,
      ...(memory ? [watchTurns(sessionManager, tracker, memory), watchHistory(tracker, memory)] : []),
      // Saves change dirty counts; refocusing catches work done in a terminal or another app.
      vscode.workspace.onDidSaveTextDocument(() => tracker.schedule()),
      vscode.window.onDidChangeWindowState((state) => state.focused && tracker.schedule())
    )
  }

  // First run: show the providers and how to start, once.
  if (!context.globalState.get('agentdeck.welcomed') && sessionManager.list().length === 0) {
    void context.globalState.update('agentdeck.welcomed', true)
    surfaces.openProviders('Welcome to AgentDeck')
  }
}

export async function deactivate(): Promise<void> {
  await manager?.dispose()
}
