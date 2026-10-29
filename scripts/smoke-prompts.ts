// Live check: a provider asks a real question and gets an answer; Claude presents a real plan for approval.
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { SessionItem } from '../src/core/types'
import { captureEnv } from '../src/env'
import { providers } from '../src/providers/registry'
import { SessionManager } from '../src/sessions/manager'
import { SessionStore } from '../src/sessions/store'
import { MemoryMemento } from '../test/memory-memento'

const TIMEOUT_MS = 240_000

async function main(): Promise<void> {
  const providerId = process.argv[2] ?? 'claude'
  if (!providers.has(providerId)) throw new Error(`Unknown provider: ${providerId}`)
  const env = await captureEnv()
  const cwd = mkdtempSync(join(tmpdir(), 'agentdeck-prompts-'))
  writeFileSync(join(cwd, 'notes.md'), '# Notes\n\nhello world\n')
  const manager = new SessionManager({
    providers,
    store: new SessionStore(new MemoryMemento()),
    journalDir: join(cwd, '.journal'),
    cwd,
    env: async () => env
  })

  const ask = await manager.create(providerId)
  const asked = await turn(manager, ask.id, 'Before anything else, ask me which color I prefer using your tool for asking the user a question, with exactly two options: Red and Blue. After I answer, reply with just the color I chose.', (item) => {
    if (item.kind === 'question' && item.resolved === undefined) {
      const question = item.questions[0]
      const blue = question.options.find((option) => /blue/i.test(option.label))
      console.log('question:', question.question, question.options.map((option) => option.label))
      manager.answer(ask.id, item.id, { kind: 'answers', answers: [{ questionId: question.id, optionIds: blue ? [blue.id] : [], ...(blue ? {} : { other: 'Blue' }) }] })
      return true
    }
    return false
  })
  console.log(asked.prompted ? `${providerId} asked: PASS` : `${providerId} asked: NOT ASKED (answered in text)`)
  if (asked.prompted && !/blue/i.test(asked.reply)) throw new Error(`answer not received: ${JSON.stringify(asked.reply)}`)

  if (providerId === 'claude') {
    const plan = await manager.create('claude', 'plan')
    const planned = await turn(manager, plan.id, 'Plan how to replace "hello world" with "goodbye world" in notes.md. Present the plan for approval when ready.', (item) => {
      if (item.kind === 'approval' && item.subject?.kind === 'plan' && item.resolved === undefined) {
        console.log('plan:', item.subject.text.slice(0, 120).replaceAll('\n', ' '))
        manager.answer(plan.id, item.id, { kind: 'option', optionId: 'approve:accept-edits' })
        return true
      }
      if (item.kind === 'approval' && item.resolved === undefined) {
        manager.answer(plan.id, item.id, { kind: 'option', optionId: 'allow' })
      }
      return false
    })
    if (!planned.prompted) throw new Error('Claude did not present a plan for approval')
    const mode = manager.list().find(({ record }) => record.id === plan.id)?.record.mode
    console.log('mode after approval:', mode)
    if (mode !== 'accept-edits') throw new Error(`mode not switched: ${mode}`)
  }
  await manager.dispose()
  console.log('PROMPTS SMOKE OK')
}

/** Sends a prompt; `onItem` answers prompts and returns true when it handled the one being tested. */
function turn(
  manager: SessionManager,
  id: string,
  text: string,
  onItem: (item: SessionItem) => boolean
): Promise<{ prompted: boolean; reply: string }> {
  return new Promise((resolve, reject) => {
    let prompted = false
    const replies = new Map<string, string>()
    const timer = setTimeout(() => reject(new Error(`turn timed out: ${text}`)), TIMEOUT_MS)
    const subscription = manager.subscribe(id, (event) => {
      if (event.type !== 'item') return
      const item = event.item
      if (onItem(item)) prompted = true
      if (item.kind === 'message' && item.role === 'assistant') replies.set(item.id, item.text)
      if (item.kind === 'notice') console.log(`notice (${item.level}):`, item.text)
      if (item.kind === 'turn' && item.state === 'ended') {
        clearTimeout(timer)
        subscription.dispose()
        resolve({ prompted, reply: [...replies.values()].join('\n') })
      }
    })
    void manager.prompt(id, [{ type: 'text', text }])
  })
}

main().catch((error) => {
  console.error('PROMPTS SMOKE FAILED:', error)
  process.exit(1)
})
