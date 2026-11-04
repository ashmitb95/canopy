// Live check: after rewinding the second message, the agent no longer knows it.
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { PromptPart, SessionItem } from '../src/core/types'
import { captureEnv } from '../src/env'
import { providers } from '../src/providers/registry'
import { SessionManager } from '../src/sessions/manager'
import { SessionStore } from '../src/sessions/store'
import { MemoryMemento } from '../test/memory-memento'

async function main(): Promise<void> {
  const providerId = process.argv[2] ?? 'claude'
  const cwd = mkdtempSync(join(tmpdir(), 'canopy-rewind-'))
  const env = await captureEnv()
  const manager = new SessionManager({ providers, store: new SessionStore(new MemoryMemento()), journalDir: join(cwd, '.journal'), cwd, env: async () => env })
  const { id } = await manager.create(providerId)
  let items: SessionItem[] = []
  manager.subscribe(id, (event) => {
    if (event.type === 'snapshot') items = event.items
    if (event.type === 'item') items = [...items.filter((item) => item.id !== event.item.id), event.item]
  })
  const turn = (text: string) =>
    new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`timed out: ${text}`)), 180_000)
      const subscription = manager.subscribe(id, (event) => {
        if (event.type === 'item' && event.item.kind === 'turn' && event.item.state === 'ended') {
          clearTimeout(timer)
          subscription.dispose()
          const reply = [...items].reverse().find((item) => item.kind === 'message' && item.role === 'assistant')
          resolve(reply?.kind === 'message' && reply.role === 'assistant' ? reply.text : '')
        }
      })
      void manager.prompt(id, [{ type: 'text', text }] as PromptPart[])
    })
  await turn('Remember the word APPLE. Reply OK.')
  await turn('Also remember the word BANANA. Reply OK.')
  const second = items.filter((item) => item.kind === 'message' && item.role === 'user')[1]
  await manager.rewind(id, second.id, false)
  const reply = await turn('List every word I asked you to remember, nothing else.')
  console.log('after rewind:', reply.replaceAll('\n', ' '))
  await manager.dispose()
  if (/banana/i.test(reply) || !/apple/i.test(reply)) throw new Error('the rewind did not take')
  console.log('REWIND SMOKE OK')
}

main().catch((error) => {
  console.error('REWIND SMOKE FAILED:', error)
  process.exit(1)
})
