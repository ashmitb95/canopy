import { relative } from 'node:path'

const MAX_FILES = 10
const MAX_REPLY = 400

export type SummaryInput = { stamp: string; title: string; provider: string; root: string; files: string[]; reply?: string }

/** A chat's summary, built from what Canopy already knows: no model call. */
export function chatSummary(input: SummaryInput): string {
  const files = [...new Set(input.files.map((file) => relative(input.root, file)))]
  const lines = [input.stamp, `# ${input.title} · ${input.provider}`]
  if (files.length > 0) {
    const more = files.length > MAX_FILES ? ` (+${files.length - MAX_FILES} more)` : ''
    lines.push(`Files: ${files.slice(0, MAX_FILES).join(', ')}${more}`)
  }
  const reply = input.reply?.replace(/\s+/g, ' ').trim()
  if (reply) lines.push(`Last reply: ${reply.length > MAX_REPLY ? `${reply.slice(0, MAX_REPLY)}…` : reply}`)
  return `${lines.join('\n')}\n`
}
