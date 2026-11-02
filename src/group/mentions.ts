export type Segment = { target?: string; text: string }

/**
 * Splits a message at each `@agent`, for known agents only, so an email address or `@types/node` stays as text.
 * Text before the first mention has no target: it goes to whoever was last addressed.
 */
export function parseMentions(text: string, agents: readonly string[]): Segment[] {
  const known = new Map(agents.map((agent) => [agent.toLowerCase(), agent]))
  const segments: Segment[] = []
  let target: string | undefined
  let start = 0
  for (const match of text.matchAll(/(^|\s)@([\w-]+)(?![\w/.-])/g)) {
    const agent = known.get(match[2].toLowerCase())
    if (!agent) continue
    const before = text.slice(start, match.index).trim()
    if (before || target) segments.push({ ...(target ? { target } : {}), text: before })
    target = agent
    start = match.index + match[0].length
  }
  segments.push({ ...(target ? { target } : {}), text: text.slice(start).trim() })
  return segments.filter((segment) => segment.text !== '')
}
