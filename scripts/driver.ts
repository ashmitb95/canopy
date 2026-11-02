// A terminal host for the core: chat, @mention, answer, and watch the stream, with no UI.
// Usage: node dist/driver.js [workspace] [--lead claude] [--lane name] [--mode full-access]
import { join, resolve } from 'node:path'
import { createInterface } from 'node:readline'
import type { PermissionMode, SessionItem } from '../src/core/types'
import { captureEnv } from '../src/env'
import type { GroupChat } from '../src/group/chat'
import { createCore } from '../src/group/host'
import { rollingLines } from '../src/group/rolling'
import { providers } from '../src/providers/registry'

const args = process.argv.slice(2)
const flag = (name: string) => {
  const index = args.indexOf(`--${name}`)
  return index >= 0 ? args[index + 1] : undefined
}
const root = resolve(args.find((arg, index) => !arg.startsWith('--') && !args[index - 1]?.startsWith('--')) ?? '.')

const HELP = `Type a message, or @agent to address one.
/state  who is doing what       /queue   what is waiting
/lead x switch lead             /lane x  put this chat on lane x
/move x run lane x in the primary checkout
/stop   stop the running agent  /send n  stop and send queued message n now
/retry  continue after a stop   /chats   list chats    /open n  open chat n
/undo   undo a move a crash left unfinished            /quit`

async function main(): Promise<void> {
  const env = await captureEnv()
  const core = await createCore({ root, storage: join(root, '.agentdeck', 'driver'), env: async () => ({ ...env, CLAUDE_NOTIFIER_DISABLE: '1' }), providers })
  const unfinished = await core.lanes.unfinishedMoves()
  if (unfinished.length > 0) console.log(`A move was left unfinished: ${unfinished.map((move) => `${move.lane} in ${move.repo}`).join(', ')}. Use /undo.`)
  const chatOptions = { lead: flag('lead') ?? 'claude', mode: (flag('mode') ?? 'ask') as PermissionMode, ...(flag('lane') ? { laneId: flag('lane') } : {}) }
  let chat: GroupChat = core.chats.list().at(-1) ?? core.chats.create(chatOptions)
  const pending: { agent: string; item: Extract<SessionItem, { kind: 'approval' | 'question' }> }[] = []
  const printed = new Map<string, string>()
  const stream = new Map<string, SessionItem[]>()
  let unsubscribe = watch(chat)

  function watch(target: GroupChat) {
    return target.onEvent((event) => {
      if (event.type !== 'item') return
      const items = stream.get(event.agent) ?? []
      items.push(event.item)
      stream.set(event.agent, items)
      for (const line of rollingLines(items, core.tracker.root)) {
        if (line.live || printed.get(`${event.agent}:${line.id}`) === line.text) continue
        printed.set(`${event.agent}:${line.id}`, line.text)
        const mark = line.kind === 'tool' ? `${line.failed ? '✗' : '·'} ` : line.kind === 'output' ? '  ' : ''
        console.log(`[${event.agent}] ${mark}${line.text}${line.stat ? `  ${line.stat}` : ''}`)
      }
      const { item } = event
      if ((item.kind === 'approval' || item.kind === 'question') && !item.resolved && !pending.some((entry) => entry.item.id === item.id)) {
        pending.push({ agent: event.agent, item })
        ask()
      }
    })
  }

  function ask(): void {
    const next = pending[0]
    if (!next) return
    if (next.item.kind === 'approval') {
      console.log(`\n${next.agent} asks: ${next.item.title}`)
      next.item.options.forEach((option, index) => console.log(`  ${index + 1}. ${option.label}`))
    } else {
      for (const question of next.item.questions) {
        console.log(`\n${next.agent} asks: ${question.question}`)
        question.options?.forEach((option, index) => console.log(`  ${index + 1}. ${option.label}`))
      }
    }
    console.log('Reply with a number, or text for a question.')
  }

  function answerPending(text: string): void {
    const next = pending.shift()
    if (!next) return
    const choice = Number(text) - 1
    if (next.item.kind === 'approval') {
      const option = next.item.options[choice] ?? next.item.options.at(-1)
      if (option) chat.answer(next.agent, next.item.id, { kind: 'option', optionId: option.id })
    } else {
      const answers = next.item.questions.map((question) => {
        const option = question.options?.[choice]
        return option ? { questionId: question.id, optionIds: [option.id] } : { questionId: question.id, optionIds: [], other: text }
      })
      chat.answer(next.agent, next.item.id, { kind: 'answers', answers })
    }
    ask()
  }

  console.log(`${root}\nChat ${chat.record.title}, lead ${chat.record.lead}. /help for commands.`)
  const input = createInterface({ input: process.stdin, output: process.stdout, terminal: false })
  for await (const raw of input) {
    const text = raw.trim()
    if (!text) continue
    try {
      if (pending.length > 0 && !text.startsWith('/')) answerPending(text)
      else if (!text.startsWith('/')) {
        for (const result of await chat.send(text)) console.log(`→ ${result.target} gets this ${result.delivery === 'now' ? 'now' : result.delivery === 'end-of-turn' ? 'when it finishes' : 'when it is up'}`)
      } else {
        const [command, value] = text.split(/\s+/, 2)
        if (command === '/help') console.log(HELP)
        if (command === '/state') console.log(JSON.stringify(chat.state(), null, 1))
        if (command === '/queue') chat.state().queue.forEach((message, index) => console.log(`${index + 1}. ${message.target}: ${message.text}`))
        if (command === '/lead') chat.setLead(value)
        if (command === '/lane') await chat.setLane(value)
        if (command === '/move') console.log((await core.lanes.moveIntoPrimary(value)).join('\n'))
        if (command === '/stop') await chat.stop()
        if (command === '/send') {
          const message = chat.state().queue[Number(value) - 1]
          if (message) await chat.stopAndSend(message.id)
        }
        if (command === '/retry') chat.retry()
        if (command === '/undo') console.log(`Undone in: ${(await core.lanes.undoUnfinishedMoves()).join(', ') || 'nothing'}`)
        if (command === '/chats') core.chats.list().forEach((other, index) => console.log(`${index + 1}. ${other.record.title} (lead ${other.record.lead})`))
        if (command === '/open') {
          const other = core.chats.list()[Number(value) - 1]
          if (other) {
            unsubscribe.dispose()
            chat = other
            unsubscribe = watch(chat)
          }
        }
        if (command === '/quit') break
      }
    } catch (error) {
      console.log(`! ${(error as Error).message}`)
    }
  }
  await core.dispose()
  process.exit(0)
}

void main()
