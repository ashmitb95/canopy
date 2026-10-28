import { describe, expect, it } from 'vitest'
import { spawnGroup, stopGroup } from '../src/process'

const exited = (child: ReturnType<typeof spawnGroup>) =>
  new Promise<void>((resolve) => child.once('exit', () => resolve()))

describe.skipIf(process.platform === 'win32')('process groups', () => {
  it('stops a CLI and the children it started', async () => {
    const child = spawnGroup('sh', ['-c', 'sleep 30 & wait'], { stdio: 'ignore' })
    const done = exited(child)
    await stopGroup(child)
    await done
    expect(child.exitCode !== null || child.signalCode !== null).toBe(true)
  })

  it('kills a CLI that ignores SIGTERM after the grace period', async () => {
    const child = spawnGroup('sh', ['-c', 'trap "" TERM; sleep 30'], { stdio: 'ignore' })
    await new Promise((resolve) => setTimeout(resolve, 100))
    const started = Date.now()
    await stopGroup(child, 200)
    expect(child.signalCode).toBe('SIGKILL')
    expect(Date.now() - started).toBeLessThan(2000)
  })

  it('does nothing for a process that already exited', async () => {
    const child = spawnGroup('sh', ['-c', 'exit 0'], { stdio: 'ignore' })
    await exited(child)
    await stopGroup(child)
  })
})
