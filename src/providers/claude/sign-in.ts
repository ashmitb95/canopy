import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { SignInEvent, SignInFlow } from '../../core/types'
import type { Env } from '../../env'
import { isClaudeSignInLink, runLoginCli } from '../sign-in'

// Claude hands its sign-in link to $BROWSER and discards the browser's stdout, so the helper writes it to a file.
const HELPER = `#!/bin/sh\nprintf '%s' "$1" > "$0.tmp" && mv "$0.tmp" "$0.link"\n`
const POLL_MS = 250

export function claudeSignIn(cliPath: string, env: Env, onEvent: (event: SignInEvent) => void): SignInFlow {
  const dir = mkdtempSync(join(tmpdir(), 'agentdeck-sign-in-'))
  const helper = join(dir, 'browser')
  writeFileSync(helper, HELPER, { mode: 0o700 })
  const cleanup = () => {
    clearInterval(poll)
    rmSync(dir, { recursive: true, force: true })
  }
  const poll = setInterval(() => {
    let link: string
    try {
      link = readFileSync(`${helper}.link`, 'utf8').trim()
    } catch {
      return
    }
    clearInterval(poll)
    if (isClaudeSignInLink(link)) onEvent({ kind: 'link', url: link })
    else onEvent({ kind: 'failed', message: 'Claude offered an unexpected sign-in link, so AgentDeck did not open it.' })
  }, POLL_MS)
  const flow = runLoginCli(cliPath, ['auth', 'login', '--claudeai'], { ...env, BROWSER: helper }, (event) => {
    if (event.kind !== 'link') cleanup()
    onEvent(event)
  }, () => null)
  return {
    cancel: () => {
      cleanup()
      flow.cancel()
    }
  }
}
