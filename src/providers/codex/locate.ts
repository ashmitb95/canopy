import { existsSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { type Env, findOnPath } from '../../env'

const EXTENSION_ROOTS = ['.vscode/extensions', '.vscode-insiders/extensions', '.cursor/extensions']
const PREFIX = 'openai.chatgpt-'

/** The codex CLI on PATH, else the one bundled with the newest official Codex extension. */
export function findCodex(env: Env, home = env.HOME ?? homedir()): string | null {
  const onPath = findOnPath(env, 'codex')
  if (onPath) return onPath
  const name = process.platform === 'win32' ? 'codex.exe' : 'codex'
  for (const root of EXTENSION_ROOTS) {
    const dir = join(home, root)
    if (!existsSync(dir)) continue
    const extensions = readdirSync(dir)
      .filter((entry) => entry.startsWith(PREFIX))
      .sort((a, b) => compareVersions(b, a))
    for (const extension of extensions) {
      const bin = join(dir, extension, 'bin')
      if (!existsSync(bin)) continue
      for (const platform of readdirSync(bin)) {
        const candidate = join(bin, platform, name)
        if (existsSync(candidate)) return candidate
      }
    }
  }
  return null
}

function compareVersions(a: string, b: string): number {
  const parse = (name: string) => (name.slice(PREFIX.length).match(/^[\d.]+/)?.[0] ?? '').split('.').map(Number)
  const [left, right] = [parse(a), parse(b)]
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    const difference = (left[i] ?? 0) - (right[i] ?? 0)
    if (difference !== 0) return difference
  }
  return 0
}
