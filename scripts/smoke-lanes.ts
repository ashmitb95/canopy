// Live check: a real agent on a lane receives its brief and can say the lane's goal; its summary lands in the lane.
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv } from '../src/env'
import { laneContext } from '../src/lanes/lane-context'
import { watchTurns } from '../src/lanes/lane-turns'
import { LaneMemory } from '../src/lanes/memory'
import { LaneTracker } from '../src/lanes/tracker'
import { providers } from '../src/providers/registry'
import { SessionManager } from '../src/sessions/manager'
import { SessionStore } from '../src/sessions/store'
import { MemoryMemento } from '../test/memory-memento'

const TIMEOUT_MS = 180_000
const GOAL = 'Teach the parser to accept trailing commas'

const git = (cwd: string, ...args: string[]) => execFileSync('git', args, { cwd, stdio: 'ignore' })

async function main(): Promise<void> {
  const providerId = process.argv[2] ?? 'claude'
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'agentdeck-lanes-smoke-')))
  const api = join(root, 'api')
  mkdirSync(api)
  git(api, 'init', '-q', '-b', 'main')
  git(api, 'config', 'user.email', 'smoke@example.com')
  git(api, 'config', 'user.name', 'Smoke')
  writeFileSync(join(api, 'parser.ts'), 'export const parse = (s: string) => JSON.parse(s)\n')
  git(api, 'add', '.')
  git(api, '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'init')
  git(api, 'checkout', '-q', '-b', 'trailing-commas')

  const tracker = new LaneTracker(root)
  const memory = new LaneMemory(tracker.root)
  memory.setGoal('trailing-commas', GOAL)
  const env = await captureEnv()
  const manager = new SessionManager({
    providers,
    store: new SessionStore(new MemoryMemento()),
    journalDir: join(root, '.journal'),
    cwd: root,
    env: async () => env,
    decorate: laneContext(tracker, memory)
  })
  watchTurns(manager, tracker, memory)
  const { id } = await manager.create(providerId)
  await manager.setLane(id, 'trailing-commas')

  const reply = await new Promise<string>((resolve, reject) => {
    const replies = new Map<string, string>()
    const timer = setTimeout(() => reject(new Error('turn timed out')), TIMEOUT_MS)
    const subscription = manager.subscribe(id, (event) => {
      if (event.type !== 'item') return
      const item = event.item
      if (item.kind === 'message' && item.role === 'assistant') replies.set(item.id, item.text)
      if (item.kind === 'approval' && item.resolved === undefined) manager.answer(id, item.id, { kind: 'option', optionId: 'deny' })
      if (item.kind === 'turn' && item.state === 'ended') {
        clearTimeout(timer)
        subscription.dispose()
        resolve([...replies.values()].join('\n'))
      }
    })
    void manager.prompt(id, [{ type: 'text', text: 'Without using any tools: what is the goal of the lane you are on, and which folder holds its code? One line.' }])
  })
  console.log('reply:', reply.replaceAll('\n', ' ').slice(0, 200))
  if (!/trailing comma/i.test(reply)) throw new Error('the agent did not see the lane goal')
  const summary = join(memory.laneDir('trailing-commas'), 'chats', `${id}.md`)
  const started = Date.now()
  while (!existsSync(summary) && Date.now() - started < 5000) await new Promise((resolve) => setTimeout(resolve, 100))
  if (!existsSync(summary)) throw new Error('no chat summary written')
  console.log('summary:', readFileSync(summary, 'utf8').split('\n').slice(0, 2).join(' | '))
  await manager.dispose()
  tracker.dispose()
  console.log('LANES SMOKE OK')
}

main().catch((error) => {
  console.error('LANES SMOKE FAILED:', error)
  process.exit(1)
})
