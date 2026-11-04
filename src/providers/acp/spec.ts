import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { type Env, findOnPath } from '../../env'

/** Everything Canopy needs to know about one ACP agent; the protocol handling is shared. */
export type AcpAgentSpec = {
  id: string
  label: string
  command: string
  installUrl: string
  /** Arguments that start the agent's ACP server on stdio. */
  args: string[]
  /** Arguments to the CLI that sign in, run in a terminal. */
  loginArgs: string[]
  /** Where the agent's installer puts the CLI, checked after PATH. */
  installDirs: (home: string) => string[]
  /** Which advertised auth method to use without prompting; undefined skips `authenticate`. */
  authMethod: (advertised: string[], env: Env) => string | undefined
  /** Whether the CLI has a usable sign-in, without starting it. */
  signedIn: (env: Env, home: string) => boolean
}

export function findAgentCli(spec: AcpAgentSpec, env: Env, home: string): string | null {
  const onPath = findOnPath(env, spec.command)
  if (onPath) return onPath
  const name = process.platform === 'win32' ? `${spec.command}.exe` : spec.command
  return spec.installDirs(home).map((dir) => join(dir, name)).find((path) => existsSync(path)) ?? null
}
