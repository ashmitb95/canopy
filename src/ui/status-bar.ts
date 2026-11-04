import * as vscode from 'vscode'
import type { SessionManager } from '../sessions/manager'

/** Running and waiting counts; hidden when nothing is active. */
export class SessionsStatusBar implements vscode.Disposable {
  private readonly item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50)
  private readonly subscription: { dispose(): void }

  constructor(private readonly manager: SessionManager) {
    this.item.command = 'canopy.sessions.focus'
    this.subscription = manager.onDidChange(() => this.update())
    this.update()
  }

  dispose(): void {
    this.subscription.dispose()
    this.item.dispose()
  }

  private update(): void {
    const sessions = this.manager.list()
    const running = sessions.filter(({ status }) => status === 'running').length
    const waiting = sessions.filter(({ status }) => status === 'needs-input').length
    if (running === 0 && waiting === 0) return this.item.hide()
    const parts = [running > 0 && `$(loading~spin) ${running} running`, waiting > 0 && `$(bell-dot) ${waiting} needs input`]
    this.item.text = parts.filter(Boolean).join('  ')
    this.item.tooltip = 'Canopy sessions'
    this.item.show()
  }
}
