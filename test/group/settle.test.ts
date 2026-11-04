import { type ChildProcess, spawn } from 'node:child_process'
import { existsSync, mkdtempSync, realpathSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { activity, baseline, stop, waitForSettled } from '../../src/group/settle'

let folder: string
const children: ChildProcess[] = []
const sh = (script: string, options: { detached?: boolean } = {}) => {
  const child = spawn('sh', ['-c', script], { cwd: folder, stdio: 'ignore', ...options })
  if (options.detached) child.unref()
  children.push(child)
  return child
}
const server = 'require("http").createServer(()=>{}).listen(0)'

beforeEach(() => {
  folder = realpathSync(mkdtempSync(join(tmpdir(), 'poc-settle-')))
})
afterEach(async () => {
  const left = await activity(folder, new Set([process.pid]))
  stop([...left.work, ...left.services].map((proc) => proc.pid))
  for (const child of children.splice(0)) child.kill()
})

describe('settling', { timeout: 30_000 }, () => {
  it('is settled at once when nothing is running', async () => {
    const outcome = await waitForSettled(folder, await baseline(folder), 5_000)
    expect(outcome.settled).toBe(true)
    expect(outcome.waitedMs).toBeLessThan(3_000)
  })

  it('ignores what ran before the turn, such as helpers', async () => {
    const helper = sh('sleep 30')
    await new Promise((resolve) => setTimeout(resolve, 300))
    const base = await baseline(folder)
    expect((await waitForSettled(folder, base, 3_000)).settled).toBe(true)
    helper.kill()
  })

  it('waits for a background command, then settles when it really ends', async () => {
    const base = await baseline(folder)
    sh('sleep 3; touch finished.txt')
    await new Promise((resolve) => setTimeout(resolve, 300))
    expect((await activity(folder, base)).work.length).toBeGreaterThan(0)
    const outcome = await waitForSettled(folder, base, 10_000)
    expect(outcome.settled).toBe(true)
    expect(existsSync(join(folder, 'finished.txt'))).toBe(true)
    expect(outcome.waitedMs).toBeGreaterThan(1_500)
  })

  it('finds a detached process by its working directory', async () => {
    const base = await baseline(folder)
    sh('nohup sh -c "sleep 3; touch detached.txt" >/dev/null 2>&1 &', { detached: true })
    await new Promise((resolve) => setTimeout(resolve, 500))
    expect((await activity(folder, base)).work.length).toBeGreaterThan(0)
    expect((await waitForSettled(folder, base, 10_000)).settled).toBe(true)
    expect(existsSync(join(folder, 'detached.txt'))).toBe(true)
  })

  it('ignores a helper a CLI starts directly mid-turn, outside any shell', async () => {
    const base = await baseline(folder)
    const helper = spawn('sleep', ['30'], { cwd: tmpdir(), stdio: 'ignore' })
    children.push(helper)
    await new Promise((resolve) => setTimeout(resolve, 300))
    expect((await activity(folder, base)).work.map((proc) => proc.pid)).not.toContain(helper.pid)
  })

  it('ignores a helper a CLI starts mid-turn in the folder, such as an MCP server', async () => {
    const base = await baseline(folder)
    const helper = spawn('sleep', ['30'], { cwd: folder, stdio: 'ignore' })
    children.push(helper)
    await new Promise((resolve) => setTimeout(resolve, 300))
    expect((await activity(folder, base)).work.map((proc) => proc.pid)).not.toContain(helper.pid)
    expect((await waitForSettled(folder, base, 3_000)).settled).toBe(true)
  })

  it('treats a process listening on a port as a service, not as work', async () => {
    const base = await baseline(folder)
    // Started in the background, so it leaves the shell's tree, as an agent's dev server does.
    sh(`node -e '${server}' >/dev/null 2>&1 &`)
    await new Promise((resolve) => setTimeout(resolve, 700))
    const outcome = await waitForSettled(folder, base, 5_000)
    expect(outcome.settled).toBe(true)
    expect(outcome.activity.services[0].ports[0]).toBeGreaterThan(0)
  })

  it('reports a timeout instead of waiting forever, and can stop the work', async () => {
    const base = await baseline(folder)
    sh('sleep 60; true')
    await new Promise((resolve) => setTimeout(resolve, 300))
    const outcome = await waitForSettled(folder, base, 1_500)
    expect(outcome.settled).toBe(false)
    stop(outcome.activity.work.map((proc) => proc.pid))
    expect((await waitForSettled(folder, base, 3_000)).settled).toBe(true)
  })
})
