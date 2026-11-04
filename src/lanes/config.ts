import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { parseToml, stringifyToml } from './toml'

export type WorkspaceConfig = {
  /** Files copied from a primary checkout into a new worktree: names or paths relative to the repo; a trailing `*` matches the rest of a name. */
  envFiles: string[]
  /** Env files per repo name, in place of `envFiles` for that repo. */
  env: Record<string, string[]>
  /** Setup command per repo name, run in a new worktree (e.g. `pnpm install`). */
  setup: Record<string, string>
  /** Whether new lanes start in worktrees; each lane can override it. */
  worktrees: boolean
  /** How many worktree slots a repo may hold. */
  maxSlots: number
}

/** `.canopy/config.toml`, with defaults for anything missing. */
export function readConfig(root: string): WorkspaceConfig {
  const path = join(root, '.canopy', 'config.toml')
  const data = existsSync(path) ? parseToml(readFileSync(path, 'utf8')) : {}
  const strings = (value: unknown) => (Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : undefined)
  const setup = typeof data.setup === 'object' && data.setup !== null && !Array.isArray(data.setup) ? data.setup : {}
  const env = typeof data.env === 'object' && data.env !== null && !Array.isArray(data.env) ? data.env : {}
  return {
    envFiles: strings(data.env_files) ?? ['.env*'],
    env: Object.fromEntries(Object.entries(env).flatMap(([repo, files]) => (strings(files)?.length ? [[repo, strings(files) ?? []]] : []))),
    setup: Object.fromEntries(Object.entries(setup).filter((entry): entry is [string, string] => typeof entry[1] === 'string')),
    worktrees: data.worktrees !== false,
    maxSlots: typeof data.max_slots === 'number' && data.max_slots > 0 ? data.max_slots : 4
  }
}

/** Writes the given settings into `.canopy/config.toml`, keeping every other key. An empty setup command removes it. */
export function updateConfig(root: string, patch: { envFiles?: string[]; env?: Record<string, string[]>; setup?: Record<string, string> }): void {
  const path = join(root, '.canopy', 'config.toml')
  const data = existsSync(path) ? parseToml(readFileSync(path, 'utf8')) : {}
  if (patch.envFiles) data.env_files = patch.envFiles
  if (patch.setup) {
    const setup: Record<string, unknown> = typeof data.setup === 'object' && data.setup !== null && !Array.isArray(data.setup) ? { ...data.setup } : {}
    for (const [repo, command] of Object.entries(patch.setup)) {
      if (command.trim()) setup[repo] = command.trim()
      else delete setup[repo]
    }
    data.setup = setup
  }
  if (patch.env) {
    // An empty list removes the repo's own list, so it uses the shared one again.
    const env: Record<string, unknown> = typeof data.env === 'object' && data.env !== null && !Array.isArray(data.env) ? { ...data.env } : {}
    for (const [repo, files] of Object.entries(patch.env)) {
      if (files.length > 0) env[repo] = files
      else delete env[repo]
    }
    data.env = env
  }
  mkdirSync(join(root, '.canopy'), { recursive: true })
  writeFileSync(path, stringifyToml(data))
}

/** The env files copied into a new worktree of this repo. */
export function envFilesFor(config: WorkspaceConfig, repo: string): string[] {
  return config.env[repo] ?? config.envFiles
}
