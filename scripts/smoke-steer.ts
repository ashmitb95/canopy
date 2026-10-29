// Live check: a queued message steered into a running turn reaches the agent within that same turn; effort can be set.
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv } from '../src/env'
import { providers } from '../src/providers/registry'
import { SessionManager } from '../src/sessions/manager'
import { SessionStore } from '../src/sessions/store'
import { MemoryMemento } from '../test/memory-memento'

async function main(): Promise<void> {
  const providerId = process.argv[2] ?? 'codex'
  const cwd = mkdtempSync(join(tmpdir(), 'agentdeck-steer-'))
  const env = await captureEnv()
  const manager = new SessionManager({ providers, store: new SessionStore(new MemoryMemento()), journalDir: join(cwd, '.journal'), cwd, env: async () => env })
  const { id } = await manager.create(providerId, 'full-access')
  let turns = 0
  let reply = ''
  let queuedId: string | undefined
  let effort: { current?: string; available: string[] } | undefined
  const done = new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timed out')), 240_000)
    manager.subscribe(id, (event) => {
      if (event.type === 'fact' && event.fact.kind === 'effort') effort = event.fact
      if (event.type === 'queue' && event.queue[0]) queuedId = event.queue[0].id
      if (event.type !== 'item') return
      if (event.item.kind === 'message' && event.item.role === 'assistant') reply = event.item.text
      if (event.item.kind === 'tool' && event.item.status === 'running' && queuedId) {
        const steering = queuedId
        queuedId = undefined
        void manager.steer(id, steering)
      }
      if (event.item.kind === 'turn' && event.item.state === 'ended') {
        turns++
        clearTimeout(timer)
        resolve()
      }
    })
  })
  await manager.warm(id)
  await new Promise((resolve) => setTimeout(resolve, 3000))
  console.log('effort levels:', effort?.available.join(', ') || '(none)')
  if (effort?.available.length) await manager.setEffort(id, effort.available[0])
  await manager.prompt(id, [{ type: 'text', text: 'Run the shell command `sleep 8 && echo done`, then reply with one line.' }])
  await manager.prompt(id, [{ type: 'text', text: 'Also: end your reply with the word PINEAPPLE.' }])
  await done
  await new Promise((resolve) => setTimeout(resolve, 2000))
  console.log(`turns ended: ${turns} · reply: ${reply.replaceAll('\n', ' ').slice(0, 160)}`)
  await manager.dispose()
  console.log(/pineapple/i.test(reply) ? 'STEER SMOKE OK' : 'STEER NOT TAKEN IN-TURN')
}

main().catch((error) => {
  console.error('STEER SMOKE FAILED:', error)
  process.exit(1)
})
