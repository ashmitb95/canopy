import type { SignInEvent, SignInFlow } from '../core/types'
import type { Env } from '../env'
import { spawnGroup, stopGroup } from '../process'

const OUTPUT_TAIL = 20_000
const CLAUDE_HOSTS = new Set(['claude.ai', 'claude.com'])
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1'])

/** Runs a CLI's own login and reports the link it offers; the CLI keeps the credentials. */
export function runLoginCli(
  command: string,
  args: string[],
  env: Env,
  onEvent: (event: SignInEvent) => void,
  findLink: (output: string) => { url: string; code?: string } | null
): SignInFlow {
  // stdin stays open: some logins wait on it while the browser step runs.
  const child = spawnGroup(command, args, { env, stdio: ['pipe', 'pipe', 'pipe'] })
  let output = ''
  let linked = false
  let settled = false
  const scan = (chunk: string) => {
    output = (output + chunk).slice(-OUTPUT_TAIL)
    if (linked) return
    const link = findLink(output)
    if (!link) return
    linked = true
    onEvent({ kind: 'link', ...link })
  }
  child.stdout?.setEncoding('utf8').on('data', scan)
  child.stderr?.setEncoding('utf8').on('data', scan)
  const settle = (event: SignInEvent) => {
    if (settled) return
    settled = true
    onEvent(event)
  }
  child.on('error', (error) => settle({ kind: 'failed', message: error.message }))
  child.on('exit', (code) =>
    settle(code === 0 ? { kind: 'done' } : { kind: 'failed', message: lastLines(output) || `Sign-in exited with ${code}.` })
  )
  return {
    cancel: () => {
      settled = true
      void stopGroup(child)
    }
  }
}

/** The first https link in a login's output, with the device code it carries, if any. */
export function deviceLink(output: string): { url: string; code?: string } | null {
  const url = output.match(/https:\/\/[^\s"'<>]+/)?.[0]
  if (!url) return null
  const code = new URL(url).searchParams.get('user_code') ?? undefined
  return code ? { url, code } : { url }
}

/** Claude's sign-in link: claude.ai or claude.com, calling back to a local port. */
export function isClaudeSignInLink(link: string): boolean {
  try {
    const url = new URL(link)
    const redirect = new URL(url.searchParams.get('redirect_uri') ?? '')
    return url.protocol === 'https:' && CLAUDE_HOSTS.has(url.hostname) && redirect.protocol === 'http:' && LOCAL_HOSTS.has(redirect.hostname)
  } catch {
    return false
  }
}

function lastLines(output: string): string {
  return output.trim().split('\n').slice(-3).join('\n').trim()
}
