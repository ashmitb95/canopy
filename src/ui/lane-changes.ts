import { relative } from 'node:path'
import * as vscode from 'vscode'
import { checkoutChanges } from '../lanes/changes'
import { git } from '../lanes/git'
import type { Lane } from '../lanes/lanes'
import type { RepoState } from '../lanes/state'

export const GIT_SCHEME = 'agentdeck-git'

type Side = { cwd?: string; ref?: string; path?: string }

/** Opens everything a lane changed, across its repos, in VS Code's multi-diff editor; serves the base side from Git. */
export class LaneChanges implements vscode.TextDocumentContentProvider {
  provideTextDocumentContent(uri: vscode.Uri): Promise<string> {
    const side = JSON.parse(uri.query) as Side
    if (!side.cwd || !side.ref || !side.path) return Promise.resolve('')
    return git(side.cwd, ['show', `${side.ref}:${side.path}`]).catch(() => '')
  }

  async open(lane: Lane, repos: RepoState[]): Promise<void> {
    const resources: [vscode.Uri, vscode.Uri, vscode.Uri][] = []
    for (const laneRepo of lane.repos) {
      const base = repos.find((repo) => repo.name === laneRepo.repo)?.base
      if (!base) continue
      for (const change of await checkoutChanges(laneRepo.path, base)) {
        const path = relative(laneRepo.path, change.path)
        const name = `${laneRepo.repo}/${path}`
        const before = change.status === 'added' ? this.uri(name, {}) : this.uri(name, { cwd: laneRepo.path, ref: change.ref, path })
        const after = change.status === 'deleted' ? this.uri(name, {}) : vscode.Uri.file(change.path)
        resources.push([vscode.Uri.file(change.path), before, after])
      }
    }
    if (resources.length === 0) return void vscode.window.showInformationMessage(`${lane.name} has no changes yet.`)
    await vscode.commands.executeCommand('vscode.changes', `${lane.name}: changes`, resources)
  }

  private uri(name: string, side: Side): vscode.Uri {
    return vscode.Uri.from({ scheme: GIT_SCHEME, path: `/${name}`, query: JSON.stringify(side) })
  }
}
