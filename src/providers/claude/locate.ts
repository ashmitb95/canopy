import { execFile } from 'node:child_process'
import { existsSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'
import { type Env, findOnPath } from '../../env'

const run = promisify(execFile)

const EXTENSION_ROOTS = ['.vscode/extensions', '.vscode-insiders/extensions', '.cursor/extensions']
const PREFIX = 'anthropic.claude-code-'

/**
 * The newest official claude CLI: the one on PATH or the one bundled with the Claude Code extension.
 * The extension updates its CLI on its own, so a standalone install can lag far behind and miss new models.
 */
export async function findClaude(env: Env, home = env.HOME ?? homedir()): Promise<string | null> {
  const candidates = [findOnPath(env, 'claude'), newestExtensionCli(home)].filter((path): path is string => !!path)
  let best: { path: string; version: number[] } | undefined
  for (const path of candidates) {
    const version = await cliVersion(path, env)
    if (version && (!best || compareVersions(version, best.version) > 0)) best = { path, version }
  }
  return best?.path ?? candidates[0] ?? null
}

function newestExtensionCli(home: string): string | null {
  const name = process.platform === 'win32' ? 'claude.exe' : 'claude'
  for (const root of EXTENSION_ROOTS) {
    const dir = join(home, root)
    if (!existsSync(dir)) continue
    const extensions = readdirSync(dir)
      .filter((entry) => entry.startsWith(PREFIX))
      .sort((a, b) => compareVersions(parseVersion(b) ?? [], parseVersion(a) ?? []))
    for (const extension of extensions) {
      const candidate = join(dir, extension, 'resources', 'native-binary', name)
      if (existsSync(candidate)) return candidate
    }
  }
  return null
}

async function cliVersion(path: string, env: Env): Promise<number[] | null> {
  try {
    const { stdout } = await run(path, ['--version'], { env, timeout: 10_000 })
    return parseVersion(stdout)
  } catch {
    return null
  }
}

function parseVersion(text: string): number[] | null {
  const match = text.match(/(\d+)\.(\d+)\.(\d+)/)
  return match ? match.slice(1).map(Number) : null
}

function compareVersions(a: number[], b: number[]): number {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const difference = (a[i] ?? 0) - (b[i] ?? 0)
    if (difference !== 0) return difference
  }
  return 0
}
