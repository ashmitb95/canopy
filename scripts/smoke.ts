// Live check outside VS Code: sign-in, MCP status, an approved edit, memory across turns, and resume.
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { SessionFact } from '../src/core/types'
import { captureEnv } from '../src/env'
import { providers } from '../src/providers/registry'
import { SessionManager } from '../src/sessions/manager'
import { SessionStore } from '../src/sessions/store'
import { MemoryMemento } from '../test/memory-memento'

const TIMEOUT_MS = 180_000

async function main(): Promise<void> {
  const providerId = process.argv[2] ?? 'claude'
  const provider = providers.get(providerId)
  if (!provider) throw new Error(`Unknown provider: ${providerId}`)
  const env = await captureEnv()
  const state = await provider.probe(env)
  console.log(`${providerId}:`, state)
  if (state.status !== 'signed-in') throw new Error(`${providerId} is not signed in`)

  const cwd = mkdtempSync(join(tmpdir(), 'agentdeck-smoke-'))
  const file = join(cwd, 'notes.md')
  writeFileSync(file, '# Notes\n\nhello world\n')
  const memento = new MemoryMemento()
  const manager = () =>
    new SessionManager({
      providers,
      store: new SessionStore(memento),
      journalDir: join(cwd, '.journal'),
      cwd,
      env: async () => env
    })

  const first = manager()
  const { id } = await first.create(providerId)
  const mcp = waitForFact(first, id, 'mcp')
  await first.warm(id)
  const servers = await mcp
  console.log('mcp before first prompt:', servers.kind === 'mcp' ? servers.servers.map((s) => `${s.name}=${s.status}`) : [])

  await turn(first, id, 'In notes.md, replace "hello world" with "goodbye world". Reply with one short sentence.')
  if (!readFileSync(file, 'utf8').includes('goodbye world')) throw new Error('edit was not applied')
  const settled = first.list().find(({ record }) => record.id === id)?.record.facts.mcp
  console.log('mcp after first turn:', settled?.kind === 'mcp' ? settled.servers.map((s) => `${s.name}=${s.status}`) : [])
  const recall = await turn(first, id, 'What word did you just replace? Answer with that single word only.')
  if (!/hello/i.test(recall)) throw new Error(`second turn lost context: ${JSON.stringify(recall)}`)
  await first.dispose()

  // A new manager over the same storage stands in for a VS Code reload.
  const second = manager()
  const resumed = await turn(second, id, 'Earlier in this conversation you replaced one word in notes.md. Which word did you remove? Answer with that single word only.')
  if (!/hello/i.test(resumed)) throw new Error(`resume lost context: ${JSON.stringify(resumed)}`)
  await second.dispose()
  console.log('SMOKE OK')
}

/** Sends a prompt, approves every tool, and returns the turn's assistant text. */
function turn(manager: SessionManager, id: string, text: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const replies = new Map<string, string>()
    const timer = setTimeout(() => reject(new Error(`turn timed out: ${text}`)), TIMEOUT_MS)
    const subscription = manager.subscribe(id, (event) => {
      if (event.type !== 'item') return
      const item = event.item
      if (item.kind === 'message' && item.role === 'assistant') replies.set(item.id, item.text)
      if (item.kind === 'approval' && !item.resolved) {
        console.log('approving:', item.title, item.detail ?? '')
        manager.answer(id, item.id, 'allow')
      }
      if (item.kind === 'tool' && item.status !== 'running') console.log(`tool ${item.status}:`, item.title)
      if (item.kind === 'notice') console.log(`notice (${item.level}):`, item.text)
      if (item.kind === 'turn' && item.state === 'ended') {
        clearTimeout(timer)
        subscription.dispose()
        const reply = [...replies.values()].join('\n')
        console.log('reply:', reply)
        resolve(reply)
      }
    })
    void manager.prompt(id, [{ type: 'text', text }])
  })
}

function waitForFact(manager: SessionManager, id: string, kind: SessionFact['kind']): Promise<SessionFact> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`no ${kind} fact`)), TIMEOUT_MS)
    const subscription = manager.subscribe(id, (event) => {
      if (event.type !== 'fact' || event.fact.kind !== kind) return
      clearTimeout(timer)
      subscription.dispose()
      resolve(event.fact)
    })
  })
}

main().catch((error) => {
  console.error('SMOKE FAILED:', error)
  process.exit(1)
})
