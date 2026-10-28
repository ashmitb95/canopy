import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { promisify } from 'node:util'

const run = promisify(execFile)

/** Environment for spawning provider CLIs. */
export type Env = Record<string, string>

const MARKER = '__AGENTDECK_PATH__'

/** GUI-launched VS Code lacks the shell's PATH, so read it from a login shell. */
export async function captureEnv(base: NodeJS.ProcessEnv = process.env): Promise<Env> {
  const env: Env = {}
  for (const [key, value] of Object.entries(base)) {
    if (value !== undefined) env[key] = value
  }
  const shell = base.SHELL
  if (shell && process.platform !== 'win32') {
    try {
      // Shell startup files may print; the marker separates their output from the PATH.
      const { stdout } = await run(shell, ['-ilc', `printf "${MARKER}%s" "$PATH"`], { timeout: 10_000 })
      const path = stdout.split(MARKER).pop()?.trim()
      if (path) env.PATH = path
    } catch {
      // Fall back to the extension host's PATH.
    }
  }
  return env
}

export function findOnPath(env: Env, command: string): string | null {
  const name = process.platform === 'win32' ? `${command}.exe` : command
  for (const dir of (env.PATH ?? '').split(delimiter)) {
    const candidate = join(dir, name)
    if (dir && existsSync(candidate)) return candidate
  }
  return null
}
