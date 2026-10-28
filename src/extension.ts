import { homedir } from 'node:os'
import { join } from 'node:path'
import * as vscode from 'vscode'
import { captureEnv, type Env } from './env'
import { claudeProvider } from './providers/claude/provider'
import { SessionManager } from './sessions/manager'
import { SessionStore } from './sessions/store'
import { ChatSurfaces, PANEL_TYPE, SIDEBAR_VIEW } from './ui/chat-surfaces'
import { DIFF_SCHEME, DiffDocuments } from './ui/diff-documents'
import { EditorContextTracker } from './ui/editor-context'
import { type SessionNode, SessionsTree } from './ui/sessions-tree'
import { SessionsStatusBar } from './ui/status-bar'

let manager: SessionManager | undefined

export function activate(context: vscode.ExtensionContext): void {
  let env: Promise<Env> | undefined
  const getEnv = () => (env ??= captureEnv())
  const providers = new Map([[claudeProvider.id, claudeProvider]])
  const storage = (context.storageUri ?? context.globalStorageUri).fsPath
  manager = new SessionManager({
    providers,
    store: new SessionStore(context.workspaceState),
    journalDir: join(storage, 'sessions'),
    cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? homedir(),
    env: getEnv
  })
  const sessionManager = manager
  const editor = new EditorContextTracker()
  const diffs = new DiffDocuments(manager)
  const surfaces = new ChatSurfaces(context, manager, providers, getEnv, editor, diffs)
  context.subscriptions.push(
    editor,
    surfaces,
    vscode.window.registerWebviewViewProvider(SIDEBAR_VIEW, surfaces, { webviewOptions: { retainContextWhenHidden: true } }),
    vscode.window.registerWebviewPanelSerializer(PANEL_TYPE, surfaces),
    vscode.commands.registerCommand('agentdeck.newChat', () => surfaces.newChat('panel')),
    vscode.commands.registerCommand('agentdeck.sidebar.newChat', () => surfaces.newChat('view')),
    vscode.commands.registerCommand('agentdeck.openInEditor', () => surfaces.openSidebarInEditor()),
    vscode.workspace.registerTextDocumentContentProvider(DIFF_SCHEME, diffs),
    new SessionsTree(sessionManager, new Map([...providers].map(([id, provider]) => [id, provider.label]))),
    new SessionsStatusBar(sessionManager),
    vscode.commands.registerCommand('agentdeck.openSession', (node: SessionNode) => surfaces.openPanel(node.id)),
    vscode.commands.registerCommand('agentdeck.openSessionInSidebar', (node: SessionNode) => surfaces.showInSidebar(node.id)),
    vscode.commands.registerCommand('agentdeck.renameSession', async (node: SessionNode) => {
      const title = await vscode.window.showInputBox({ prompt: 'Session name', value: node.title })
      if (title?.trim()) await sessionManager.rename(node.id, title.trim())
    }),
    vscode.commands.registerCommand('agentdeck.stopSession', (node: SessionNode) => sessionManager.stop(node.id)),
    vscode.commands.registerCommand('agentdeck.deleteSession', async (node: SessionNode) => {
      const choice = await vscode.window.showWarningMessage(`Delete “${node.title}”?`, { modal: true }, 'Delete')
      if (choice === 'Delete') await sessionManager.delete(node.id)
    })
  )
}

export async function deactivate(): Promise<void> {
  await manager?.dispose()
}
