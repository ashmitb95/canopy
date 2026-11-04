// Live check: an agent on a lane in a worktree is asked to write into the primary checkout; the write must not land there.
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, realpathSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv } from '../src/env'
import { LaneCoordinator } from '../src/lanes/coordinator'
import { laneContext } from '../src/lanes/lane-context'
import { LaneMemory } from '../src/lanes/memory'
import { LaneTracker } from '../src/lanes/tracker'
import { providers } from '../src/providers/registry'
import { SessionManager } from '../src/sessions/manager'
import { SessionStore } from '../src/sessions/store'
import { MemoryMemento } from '../test/memory-memento'

const TIMEOUT_MS = 240_000
const git = (cwd: string, ...args: string[]) => execFileSync('git', args, { cwd, stdio: 'ignore' })

async function main(): Promise<void> {
  const providerId = process.argv[2] ?? 'claude'
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'canopy-boundary-')))
  const api = join(root, 'api')
  mkdirSync(api)
  git(api, 'init', '-q', '-b', 'main')
  git(api, 'config', 'user.email', 'smoke@example.com')
  git(api, 'config', 'user.name', 'Smoke')
  writeFileSync(join(api, 'README.md'), '# api\n')
  git(api, 'add', '.')
  git(api, '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'init')

  const tracker = new LaneTracker(root)
  const memory = new LaneMemory(tracker.root)
  const env = await captureEnv()
  let coordinator: LaneCoordinator | undefined
  const manager = new SessionManager({
    providers,
    store: new SessionStore(new MemoryMemento()),
    journalDir: join(root, '.journal'),
    cwd: root,
    env: async () => env,
    decorate: laneContext(tracker, memory),
    boundary: async (record) => coordinator?.boundary(record)
  })
  coordinator = new LaneCoordinator({ tracker, memory, manager, env: async () => process.env })
  await coordinator.newLane('hello', ['api'], { worktrees: true, goal: 'Add hello.txt' })
  const { id } = await manager.create(providerId, 'full-access')
  await manager.setLane(id, 'hello')

  const target = join(api, 'hello.txt')
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('turn timed out')), TIMEOUT_MS)
    const subscription = manager.subscribe(id, (event) => {
      if (event.type !== 'item') return
      const item = event.item
      if (item.kind === 'notice') console.log(`notice (${item.level}):`, item.text.split('\n')[0])
      if (item.kind === 'approval' && item.resolved === undefined) manager.answer(id, item.id, { kind: 'option', optionId: 'allow' })
      if (item.kind === 'turn' && item.state === 'ended') {
        clearTimeout(timer)
        subscription.dispose()
        resolve()
      }
    })
    void manager.prompt(id, [{ type: 'text', text: `Create the file ${target} containing the word hi. Use your file editing tool.` }])
  })
  const inMain = existsSync(target)
  const inLane = existsSync(join(api, '.worktrees', 'wt-1', 'hello.txt'))
  console.log(`primary checkout has hello.txt: ${inMain} · lane worktree has hello.txt: ${inLane}`)
  await manager.dispose()
  tracker.dispose()
  if (inMain) throw new Error('the write landed in the primary checkout')
  console.log('BOUNDARY SMOKE OK')
}

main().catch((error) => {
  console.error('BOUNDARY SMOKE FAILED:', error)
  process.exit(1)
})
