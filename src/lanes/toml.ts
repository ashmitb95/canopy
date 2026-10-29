/**
 * The TOML subset AgentDeck writes: `[table]` headers and `key = value` lines whose value is JSON
 * (strings, numbers, booleans, arrays). JSON values are valid TOML; lines outside the subset are skipped.
 */
export function parseToml(text: string): Record<string, unknown> {
  const root: Record<string, unknown> = {}
  let table = root
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const header = /^\[([A-Za-z0-9_.-]+)\]$/.exec(line)
    if (header) {
      table = {}
      root[header[1]] = table
      continue
    }
    const pair = /^([A-Za-z0-9_-]+)\s*=\s*(.+)$/.exec(line)
    if (!pair) continue
    try {
      table[pair[1]] = JSON.parse(pair[2])
    } catch {
      // Not in the subset.
    }
  }
  return root
}

const isTable = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

export function stringifyToml(data: Record<string, unknown>): string {
  const line = ([key, value]: [string, unknown]) => `${key} = ${JSON.stringify(value)}`
  const entries = Object.entries(data)
  const lines = entries.filter(([, value]) => !isTable(value)).map(line)
  for (const [name, table] of entries) {
    if (isTable(table)) lines.push('', `[${name}]`, ...Object.entries(table).map(line))
  }
  return `${lines.join('\n')}\n`
}
