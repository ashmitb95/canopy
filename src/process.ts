import { type ChildProcess, type SpawnOptions, spawn } from 'node:child_process'

/** Spawns a CLI as the leader of its own process group, so stopping it also stops what it started. */
export function spawnGroup(command: string, args: string[], options: SpawnOptions): ChildProcess {
  return spawn(command, args, { ...options, detached: process.platform !== 'win32' })
}

/** SIGTERM to the process group, then SIGKILL after the grace period. Windows uses taskkill on the tree. */
export async function stopGroup(child: ChildProcess, graceMs = 2000): Promise<void> {
  const pid = child.pid
  if (pid === undefined || child.exitCode !== null || child.signalCode !== null) return
  const exited = new Promise<void>((resolve) => child.once('exit', () => resolve()))
  if (process.platform === 'win32') {
    spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore' })
    await exited
    return
  }
  signal(-pid, 'SIGTERM')
  const timer = setTimeout(() => signal(-pid, 'SIGKILL'), graceMs)
  await exited
  clearTimeout(timer)
}

function signal(pid: number, name: NodeJS.Signals): void {
  try {
    process.kill(pid, name)
  } catch {
    // The group is already gone.
  }
}
