import { exec, execFile } from 'node:child_process'
import { accessSync, constants } from 'node:fs'
import { basename, join } from 'node:path'
import * as vscode from 'vscode'
import type { Disposable } from '../core/emitter'
import { banner, type ChatLabel, type NotifyEvent } from '../notify/compose'
import { popupCommand } from '../notify/popup'
import { type Command, soundCommand } from '../notify/sound'
import type { Attention, SessionManager } from '../sessions/manager'

type Level = 'sound+popup' | 'sound' | 'popup' | 'off'

function run(command: Command): void {
  if ('file' in command) execFile(command.file, command.args, () => {})
  else exec(command.shell, { timeout: 10_000 }, () => {})
}

function findTerminalNotifier(): string | undefined {
  if (process.platform !== 'darwin') return undefined
  for (const candidate of ['/opt/homebrew/bin/terminal-notifier', '/usr/local/bin/terminal-notifier']) {
    try {
      accessSync(candidate, constants.X_OK)
      return candidate
    } catch {
      // Not here.
    }
  }
  return undefined
}

/** Native notifications from AgentDeck's own session events (decision 35). */
export class Notifier implements vscode.Disposable {
  private readonly subscription: Disposable
  private readonly terminalNotifier = findTerminalNotifier()

  constructor(
    private readonly manager: SessionManager,
    private readonly labels: ReadonlyMap<string, string>,
    private readonly isVisible: (sessionId: string) => boolean
  ) {
    this.subscription = manager.onAttention((attention) => this.notify(attention))
  }

  /** Shows one notification of the given event for the most recent chat, for trying settings out. */
  test(event: NotifyEvent): void {
    const record = this.manager.list()[0]?.record
    const chat: ChatLabel = { workspace: this.workspace(), provider: record ? this.label(record.providerId) : 'Claude', title: record?.title ?? 'Test chat' }
    const detail =
      event === 'finished'
        ? ({ reason: 'turn-ended', durationMs: 60_000, edits: 2, commands: 3 } as const)
        : event === 'failed'
          ? ({ reason: 'failed', text: 'Something went wrong' } as const)
          : ({ reason: 'needs-input', prompt: { kind: event === 'approval' ? 'approval' : 'question', text: event === 'approval' ? 'Allow Bash?: pnpm test' : 'Which option?' } } as const)
    this.deliver(event, banner(chat, detail), true)
  }

  dispose(): void {
    this.subscription.dispose()
  }

  private notify(attention: Attention): void {
    const record = this.manager.list().find((entry) => entry.record.id === attention.sessionId)?.record
    if (!record) return
    const config = vscode.workspace.getConfiguration('agentdeck.notifications')
    if (attention.reason === 'turn-ended' && attention.durationMs < config.get<number>('minDurationSeconds', 10) * 1000) return
    if (config.get<boolean>('muteWhenFocused', true) && vscode.window.state.focused && this.isVisible(record.id)) return
    const { sessionId: _id, ...detail } = attention
    const shown = banner(
      { workspace: this.workspace(), ...(record.laneId ? { lane: record.laneId } : {}), provider: this.label(record.providerId), title: record.title },
      detail
    )
    this.deliver(shown.event, shown, false)
  }

  private deliver(event: NotifyEvent, shown: { title: string; body: string }, force: boolean): void {
    const config = vscode.workspace.getConfiguration('agentdeck.notifications')
    const level = config.get<Level>(`${event}.level`, 'sound+popup')
    if (level === 'off' && !force) return
    if (level.includes('sound') || force) {
      run(soundCommand(process.platform, config.get<string>(`${event}.sound`, 'Hero'), config.get<number>('volume', 1)))
    }
    if (level.includes('popup') || force) {
      const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
      const codeCli = join(vscode.env.appRoot, 'bin', 'code')
      const focus = folder ? `'${codeCli.replace(/'/g, `'\\''`)}' '${folder.replace(/'/g, `'\\''`)}'` : undefined
      run(popupCommand(process.platform, shown.title, shown.body, { terminalNotifier: this.terminalNotifier, focus }))
    }
  }

  private workspace(): string {
    const file = vscode.workspace.workspaceFile
    if (file?.scheme === 'file') return basename(file.fsPath).replace(/\.code-workspace$/, '')
    return vscode.workspace.workspaceFolders?.[0]?.name ?? 'AgentDeck'
  }

  private label(providerId: string): string {
    return this.labels.get(providerId) ?? providerId
  }
}
