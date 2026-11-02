import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { parseToml } from './toml'

export type WorkspaceConfig = {
  /** Files copied from a primary checkout into a new worktree: names or paths relative to the repo; a trailing `*` matches the rest of a name. */
  envFiles: string[]
  /** Setup command per repo name, run in a new worktree (e.g. `pnpm install`). */
  setup: Record<string, string>
  /** Whether new lanes start in worktrees; each lane can override it. */
  worktrees: boolean
  /** How many worktree slots a repo may hold. */
  maxSlots: number
}

/** `.agentdeck/config.toml`, with defaults for anything missing. */
export function readConfig(root: string): WorkspaceConfig {
  const path = join(root, '.agentdeck', 'config.toml')
  const data = existsSync(path) ? parseToml(readFileSync(path, 'utf8')) : {}
  const strings = (value: unknown) => (Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : undefined)
  const setup = typeof data.setup === 'object' && data.setup !== null && !Array.isArray(data.setup) ? data.setup : {}
  return {
    envFiles: strings(data.env_files) ?? ['.env*'],
    setup: Object.fromEntries(Object.entries(setup).filter((entry): entry is [string, string] => typeof entry[1] === 'string')),
    worktrees: data.worktrees !== false,
    maxSlots: typeof data.max_slots === 'number' && data.max_slots > 0 ? data.max_slots : 4
  }
}
