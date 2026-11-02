import { exec } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, readdirSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'

const SETUP_TIMEOUT_MS = 10 * 60_000
const OUTPUT_LINES = 20

/** Files in `from` matching the patterns: a trailing `*` matches the rest of a top-level name; other patterns are exact paths. */
export function matchEnvFiles(from: string, patterns: string[]): string[] {
  const top = existsSync(from) ? readdirSync(from) : []
  return [
    ...new Set(
      patterns.flatMap((pattern) =>
        pattern.endsWith('*')
          ? top.filter((name) => name.startsWith(pattern.slice(0, -1)))
          : existsSync(join(from, pattern))
            ? [pattern]
            : []
      )
    )
  ].filter((name) => statSync(join(from, name)).isFile())
}

export type WarmResult = { copied: string[]; setup?: { command: string; ok: boolean; output: string } }

/** Readies a checkout outside the primary checkout: copies env files from the primary checkout (never overwriting), then runs the setup command. */
export async function warmUp(
  primary: string,
  target: string,
  envFiles: string[],
  setup: string | undefined,
  env: NodeJS.ProcessEnv = process.env
): Promise<WarmResult> {
  const copied = matchEnvFiles(primary, envFiles).filter((name) => !existsSync(join(target, name)))
  for (const name of copied) {
    mkdirSync(dirname(join(target, name)), { recursive: true })
    copyFileSync(join(primary, name), join(target, name))
  }
  if (!setup) return { copied }
  const outcome = await new Promise<{ ok: boolean; output: string }>((resolve) =>
    exec(setup, { cwd: target, env, timeout: SETUP_TIMEOUT_MS, maxBuffer: 32 * 1024 * 1024 }, (error, stdout, stderr) =>
      resolve({ ok: !error, output: `${stdout}${stderr}`.trim().split('\n').slice(-OUTPUT_LINES).join('\n') })
    )
  )
  return { copied, setup: { command: setup, ...outcome } }
}
