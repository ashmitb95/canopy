import * as vscode from 'vscode'
import type { FileMatch } from './protocol'
import { rankFiles } from './rank-files'

const EXCLUDE = '**/{node_modules,.git,dist,out,build,.next,coverage}/**'
const MAX_FILES = 20_000

/** Workspace files for the @ menu, listed once and listed again after files are created or deleted. */
export class FileSearch implements vscode.Disposable {
  private files: Promise<Map<string, string>> | undefined
  private readonly watcher = vscode.workspace.createFileSystemWatcher('**/*', false, true, false)
  private readonly subscriptions = [
    this.watcher,
    this.watcher.onDidCreate(() => (this.files = undefined)),
    this.watcher.onDidDelete(() => (this.files = undefined))
  ]

  async search(query: string): Promise<FileMatch[]> {
    // findFiles returns a Thenable; Promise.resolve makes it a Promise that can be cached and awaited.
    this.files ??= Promise.resolve(vscode.workspace.findFiles('**/*', EXCLUDE, MAX_FILES)).then(
      (uris) => new Map(uris.map((uri) => [vscode.workspace.asRelativePath(uri), uri.fsPath]))
    )
    const files = await this.files
    const recent = new Set(
      vscode.window.tabGroups.all
        .flatMap((group) => group.tabs)
        .flatMap((tab) => (tab.input instanceof vscode.TabInputText ? [vscode.workspace.asRelativePath(tab.input.uri)] : []))
    )
    return rankFiles([...files.keys()], query, recent).map((label) => ({ label, path: files.get(label) ?? label }))
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose()
  }
}
