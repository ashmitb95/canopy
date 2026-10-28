import * as vscode from 'vscode'
import type { PromptPart } from '../core/types'
import type { EditorContext } from './protocol'

/** The file and selection a prompt refers to. A chat webview takes focus, so the last file editor is remembered. */
export class EditorContextTracker implements vscode.Disposable {
  private last: vscode.TextEditor | undefined
  private readonly changed = new vscode.EventEmitter<EditorContext | null>()
  readonly onDidChange = this.changed.event
  private readonly subscriptions: vscode.Disposable[]

  constructor() {
    const active = vscode.window.activeTextEditor
    this.last = isFileEditor(active) ? active : undefined
    this.subscriptions = [
      this.changed,
      vscode.window.onDidChangeActiveTextEditor((editor) => {
        if (!isFileEditor(editor)) return
        this.last = editor
        this.changed.fire(this.current())
      }),
      vscode.window.onDidChangeTextEditorSelection(({ textEditor }) => {
        if (textEditor === this.last) this.changed.fire(this.current())
      }),
      vscode.workspace.onDidCloseTextDocument((document) => {
        if (document !== this.last?.document) return
        this.last = undefined
        this.changed.fire(this.current())
      })
    ]
  }

  current(): EditorContext | null {
    const editor = this.last ?? vscode.window.visibleTextEditors.find(isFileEditor)
    if (!editor) return null
    const { selection } = editor
    return {
      path: editor.document.uri.fsPath,
      label: vscode.workspace.asRelativePath(editor.document.uri),
      range: selection.isEmpty ? undefined : [selection.start.line + 1, selection.end.line + 1]
    }
  }

  part(): PromptPart | null {
    const context = this.current()
    return context ? { type: 'file', path: context.path, range: context.range } : null
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose()
  }
}

function isFileEditor(editor: vscode.TextEditor | undefined): editor is vscode.TextEditor {
  return editor?.document.uri.scheme === 'file'
}
