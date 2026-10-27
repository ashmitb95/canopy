import { randomBytes } from 'node:crypto'
import { homedir } from 'node:os'
import * as vscode from 'vscode'
import { ClaudeChat, claudeAuthStatus, resolveClaudeCli, type ChatEvent } from './claude-session'

/** Messages from the webview. */
type WebviewMessage =
  | { type: 'ready' }
  | { type: 'send'; text: string }
  | { type: 'interrupt' }
  | { type: 'permission'; id: string; allow: boolean }
  | { type: 'signIn' }

export function activate(context: vscode.ExtensionContext): void {
  // The chat tab takes focus, so remember the last real editor for "this file" prompts.
  let lastEditor = vscode.window.activeTextEditor
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor) lastEditor = editor
    }),
    vscode.commands.registerCommand('agentdeck.newClaudeChat', () => openChat(context, () => lastEditor))
  )
}

function openChat(context: vscode.ExtensionContext, activeEditor: () => vscode.TextEditor | undefined): void {
  const panel = vscode.window.createWebviewPanel('agentdeck.chat', 'Claude', vscode.ViewColumn.Beside, {
    enableScripts: true,
    retainContextWhenHidden: true,
    localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'media')]
  })
  panel.webview.html = chatHtml(panel.webview, context.extensionUri)

  const post = (message: ChatEvent | { type: 'status'; text: string; signedIn: boolean }) =>
    void panel.webview.postMessage(message)
  const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? homedir()
  let chat: ClaudeChat | null = null

  const connect = async (): Promise<void> => {
    const cli = await resolveClaudeCli()
    if (!cli) {
      post({ type: 'status', text: 'claude CLI not found. Install Claude Code, then reopen this chat.', signedIn: false })
      return
    }
    const auth = await claudeAuthStatus(cli)
    if (!auth.loggedIn) {
      post({ type: 'status', text: 'Not signed in to Claude.', signedIn: false })
      return
    }
    post({ type: 'status', text: `Signed in as ${auth.email ?? 'unknown'} (${auth.authMethod})`, signedIn: true })
    chat?.close()
    chat = new ClaudeChat(cli, cwd, post)
  }

  panel.webview.onDidReceiveMessage((message: WebviewMessage) => {
    switch (message.type) {
      case 'ready':
        void connect()
        return
      case 'send': {
        const file = activeEditor()?.document
        const context =
          file && file.uri.scheme === 'file'
            ? `\n\n<context>The file open in the user's editor is ${vscode.workspace.asRelativePath(file.uri)}</context>`
            : ''
        chat?.send(message.text + context)
        return
      }
      case 'interrupt':
        void chat?.interrupt()
        return
      case 'permission':
        chat?.respondToPermission(message.id, message.allow)
        return
      case 'signIn': {
        const terminal = vscode.window.createTerminal('Claude sign-in')
        terminal.show()
        terminal.sendText('claude auth login --claudeai')
        return
      }
    }
  })
  panel.onDidDispose(() => chat?.close())
}

function chatHtml(webview: vscode.Webview, extensionUri: vscode.Uri): string {
  const nonce = randomBytes(16).toString('base64')
  const script = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', 'chat.js'))
  const style = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', 'chat.css'))
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="${style}">
</head>
<body>
<div id="status">Connecting…<button id="sign-in" hidden>Sign in</button></div>
<div id="log"></div>
<form id="composer">
  <textarea id="prompt" rows="3" placeholder="Ask Claude… (Enter to send, Shift+Enter for newline)"></textarea>
  <div class="actions"><button type="button" id="stop">Stop</button><button type="submit" id="send">Send</button></div>
</form>
<script nonce="${nonce}" src="${script}"></script>
</body>
</html>`
}

export function deactivate(): void {}
