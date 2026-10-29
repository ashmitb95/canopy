import type { Attention } from '../sessions/manager'

// From claude-notifier: ~40 characters per banner line, four body lines.
const LINE = 40
const BODY_LINES = 4
const CHROME = 4

export const EVENTS = {
  finished: '✅ finished',
  approval: '❗ needs approval',
  question: '❓ question',
  failed: '✖ failed'
} as const

export type NotifyEvent = keyof typeof EVENTS

function truncate(text: string, max: number): string {
  if (text.length <= max) return text
  const cut = text.slice(0, max - 1)
  const space = cut.lastIndexOf(' ')
  return `${space > max / 2 ? cut.slice(0, space) : cut}…`
}

/** The banner frame: the detail takes the lines it needs, the chat title the rest. */
export function compose(input: { workspace: string; event: string; chat: string; detail: string[] }): { title: string; body: string } {
  const spare = Math.max(1, BODY_LINES - input.detail.length - (input.detail.length > 0 ? 1 : 0))
  const lines = [`• ${truncate(input.chat, spare * LINE - CHROME)} •`]
  if (input.detail.length > 0) lines.push('', ...input.detail)
  return { title: `${input.workspace} | ${input.event}`, body: lines.join('\n') }
}

export type ChatLabel = { workspace: string; lane?: string; provider: string; title: string }
type AttentionDetail = Attention extends infer A ? (A extends { sessionId: string } ? Omit<A, 'sessionId'> : never) : never

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`

function work(edits: number, commands: number): string {
  const parts = [edits > 0 ? `Edited ${plural(edits, 'file')}` : '', commands > 0 ? `ran ${plural(commands, 'command')}` : ''].filter(Boolean)
  if (parts.length === 0) return 'Replied'
  const text = parts.join(' · ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** What the notification says for an attention event. */
export function banner(chat: ChatLabel, attention: AttentionDetail): { event: NotifyEvent; title: string; body: string } {
  const label = `${chat.lane ? `${chat.lane} · ` : ''}${chat.provider}: ${chat.title}`
  const [event, detail]: [NotifyEvent, string] =
    attention.reason === 'turn-ended'
      ? ['finished', work(attention.edits, attention.commands)]
      : attention.reason === 'failed'
        ? ['failed', attention.text.split('\n')[0]]
        : [attention.prompt.kind === 'approval' ? 'approval' : 'question', attention.prompt.text]
  return { event, ...compose({ workspace: chat.workspace, event: EVENTS[event], chat: label, detail: [truncate(detail, LINE * 2)] }) }
}
