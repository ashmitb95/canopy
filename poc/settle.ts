// Proof of concept: whether work has really stopped, whatever a delegate reports.
import { execFile } from 'node:child_process'
import { realpathSync } from 'node:fs'
import { sep } from 'node:path'
import { promisify } from 'node:util'

const exec = promisify(execFile)
const run = async (file: string, args: string[]) => (await exec(file, args, { maxBuffer: 64 * 1024 * 1024 }).catch((error: { stdout?: string }) => ({ stdout: error.stdout ?? '' }))).stdout

export type Proc = { pid: number; ppid: number; state: string; command: string }

export async function processes(): Promise<Proc[]> {
  return (await run('ps', ['-axo', 'pid=,ppid=,stat=,command=']))
    .split('\n')
    .flatMap((line) => {
      const match = /^\s*(\d+)\s+(\d+)\s+(\S+)\s+(.*)$/.exec(line)
      return match ? [{ pid: Number(match[1]), ppid: Number(match[2]), state: match[3], command: match[4] }] : []
    })
}

export function descendants(all: Proc[], root: number): Set<number> {
  const found = new Set<number>()
  let grew = true
  while (grew) {
    grew = false
    for (const proc of all) {
      if ((proc.ppid === root || found.has(proc.ppid)) && !found.has(proc.pid)) {
        found.add(proc.pid)
        grew = true
      }
    }
  }
  return found
}

/** Processes whose working directory is inside a folder, which finds detached ones the process tree loses. */
export async function workingIn(folder: string): Promise<Set<number>> {
  const real = realpathSync(folder)
  const found = new Set<number>()
  let pid = 0
  for (const line of (await run('lsof', ['-a', '-d', 'cwd', '-Fpn'])).split('\n')) {
    if (line.startsWith('p')) pid = Number(line.slice(1))
    if (line.startsWith('n') && (line.slice(1) === real || line.slice(1).startsWith(real + sep))) found.add(pid)
  }
  return found
}

/** The ports each process listens on, which marks it as a service nobody should wait for. */
export async function listeners(pids: number[]): Promise<Map<number, number[]>> {
  const ports = new Map<number, number[]>()
  if (pids.length === 0) return ports
  let pid = 0
  for (const line of (await run('lsof', ['-a', '-iTCP', '-sTCP:LISTEN', '-P', '-n', '-p', pids.join(','), '-Fpn'])).split('\n')) {
    if (line.startsWith('p')) pid = Number(line.slice(1))
    const port = line.startsWith('n') ? /:(\d+)$/.exec(line)?.[1] : undefined
    if (port) ports.set(pid, [...(ports.get(pid) ?? []), Number(port)])
  }
  return ports
}

export type Activity = { work: Proc[]; services: (Proc & { ports: number[] })[] }

/** A folder's baseline: what runs before a turn, such as a CLI's MCP helpers, is not that turn's work. */
export async function baseline(folder: string, root = process.pid): Promise<Set<number>> {
  const all = await processes()
  return new Set([...descendants(all, root), ...(await workingIn(folder)), process.pid])
}

const OURS = /^(ps|lsof|git)\b|\/(ps|lsof)\b/

/** What is still running for this turn. Shells only waiting on children count through those children. */
export async function activity(folder: string, base: Set<number>, root = process.pid): Promise<Activity> {
  const all = await processes()
  const candidates = new Set([...descendants(all, root), ...(await workingIn(folder))])
  const live = all.filter((proc) => candidates.has(proc.pid) && !base.has(proc.pid) && !proc.state.startsWith('Z') && !OURS.test(proc.command))
  const ports = await listeners(live.map((proc) => proc.pid))
  const services = live.flatMap((proc) => (ports.has(proc.pid) ? [{ ...proc, ports: ports.get(proc.pid) ?? [] }] : []))
  return { services, work: live.filter((proc) => !ports.has(proc.pid)) }
}

export function stop(pids: number[]): void {
  for (const pid of pids) {
    try {
      process.kill(pid, 'SIGTERM')
    } catch {
      // Already gone.
    }
  }
}

export type Outcome = { settled: boolean; activity: Activity; waitedMs: number }

/** Waits until only services remain, or the limit passes. The caller decides what a timeout means. */
export async function waitForSettled(folder: string, base: Set<number>, limitMs: number, pollMs = 500): Promise<Outcome> {
  const started = Date.now()
  let quiet = 0
  for (;;) {
    const now = await activity(folder, base)
    quiet = now.work.length === 0 ? quiet + 1 : 0
    // Two quiet polls, so a command starting right after another is not missed.
    if (quiet >= 2) return { settled: true, activity: now, waitedMs: Date.now() - started }
    if (Date.now() - started >= limitMs) return { settled: false, activity: now, waitedMs: Date.now() - started }
    await new Promise((resolve) => setTimeout(resolve, pollMs))
  }
}
