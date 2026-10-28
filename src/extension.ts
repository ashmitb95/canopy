import { homedir } from 'node:os'
import { join } from 'node:path'
import * as vscode from 'vscode'
import { captureEnv, type Env } from './env'
import { claudeProvider } from './providers/claude/provider'
import { SessionManager } from './sessions/manager'
import { SessionStore } from './sessions/store'
import { ChatSurfaces, PANEL_TYPE, SIDEBAR_VIEW } from './ui/chat-surfaces'
import { EditorContextTracker } from './ui/editor-context'

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
  const editor = new EditorContextTracker()
  const surfaces = new ChatSurfaces(context, manager, providers, getEnv, editor)
  context.subscriptions.push(
    editor,
    surfaces,
    vscode.window.registerWebviewViewProvider(SIDEBAR_VIEW, surfaces, { webviewOptions: { retainContextWhenHidden: true } }),
    vscode.window.registerWebviewPanelSerializer(PANEL_TYPE, surfaces),
    vscode.commands.registerCommand('agentdeck.newChat', () => surfaces.newChat('panel')),
    vscode.commands.registerCommand('agentdeck.sidebar.newChat', () => surfaces.newChat('view')),
    vscode.commands.registerCommand('agentdeck.openInEditor', () => surfaces.openSidebarInEditor())
  )
}

export async function deactivate(): Promise<void> {
  await manager?.dispose()
}
