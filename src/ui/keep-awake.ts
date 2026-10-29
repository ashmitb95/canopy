import { type ChildProcess, spawn } from 'node:child_process'
import * as vscode from 'vscode'
import type { SessionManager } from '../sessions/manager'

/** Holds off idle sleep while any chat is running: caffeinate on macOS, systemd-inhibit on Linux. */
export class KeepAwake implements vscode.Disposable {
  private child: ChildProcess | undefined
  private readonly subscription: { dispose(): void }

  constructor(private readonly manager: SessionManager) {
    this.subscription = manager.onDidChange(() => this.update())
  }

  dispose(): void {
    this.subscription.dispose()
    this.release()
  }

  private update(): void {
    const enabled = vscode.workspace.getConfiguration('agentdeck').get<boolean>('keepAwake', true)
    const running = this.manager.list().some(({ status }) => status === 'running' || status === 'needs-input')
    if (enabled && running) this.hold()
    else this.release()
  }

  private hold(): void {
    if (this.child) return
    const command =
      process.platform === 'darwin'
        ? ['caffeinate', ['-i', '-w', String(process.pid)]]
        : process.platform === 'linux'
          ? ['systemd-inhibit', ['--what=idle:sleep', '--who=AgentDeck', '--why=An agent is running', 'sleep', 'infinity']]
          : undefined
    if (!command) return
    const child = spawn(command[0] as string, command[1] as string[], { stdio: 'ignore' })
    child.on('error', () => (this.child = undefined))
    child.on('exit', () => (this.child = undefined))
    this.child = child
  }

  private release(): void {
    this.child?.kill()
    this.child = undefined
  }
}
