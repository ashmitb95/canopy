import { chmodSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { SignInEvent } from '../../src/core/types'
import { deviceLink, isClaudeSignInLink, runLoginCli } from '../../src/providers/sign-in'

function script(body: string): string {
  const path = join(mkdtempSync(join(tmpdir(), 'canopy-login-')), 'login')
  writeFileSync(path, `#!/bin/sh\n${body}\n`)
  chmodSync(path, 0o755)
  return path
}

function collect(run: (onEvent: (event: SignInEvent) => void) => void): Promise<SignInEvent[]> {
  return new Promise((resolve) => {
    const events: SignInEvent[] = []
    run((event) => {
      events.push(event)
      if (event.kind !== 'link') resolve(events)
    })
  })
}

describe('deviceLink', () => {
  it('finds the link and the code it carries', () => {
    const output = 'To sign in, open this URL in your browser:\n\n  https://accounts.x.ai/oauth2/device?user_code=KWMT-AT8W\n\nWaiting…'
    expect(deviceLink(output)).toEqual({ url: 'https://accounts.x.ai/oauth2/device?user_code=KWMT-AT8W', code: 'KWMT-AT8W' })
  })

  it('returns a link without a code, and null without a link', () => {
    expect(deviceLink('Open https://example.com/login now')).toEqual({ url: 'https://example.com/login' })
    expect(deviceLink('Starting…')).toBeNull()
  })
})

describe('isClaudeSignInLink', () => {
  it('accepts claude.ai links that call back to localhost', () => {
    expect(isClaudeSignInLink('https://claude.ai/oauth/authorize?redirect_uri=http%3A%2F%2Flocalhost%3A54545%2Fcallback')).toBe(true)
    expect(isClaudeSignInLink('https://claude.com/oauth/authorize?redirect_uri=http%3A%2F%2F127.0.0.1%3A5%2Fcb')).toBe(true)
  })

  it('rejects other hosts and redirects', () => {
    expect(isClaudeSignInLink('https://evil.example/oauth?redirect_uri=http%3A%2F%2Flocalhost%2F')).toBe(false)
    expect(isClaudeSignInLink('https://claude.ai/oauth/authorize?redirect_uri=https%3A%2F%2Fevil.example%2F')).toBe(false)
    expect(isClaudeSignInLink('not a url')).toBe(false)
  })
})

describe.skipIf(process.platform === 'win32')('runLoginCli', () => {
  it('reports the link, then success', async () => {
    const cli = script('echo "open https://accounts.x.ai/oauth2/device?user_code=AB12-CD34"; sleep 0.2; echo "Signed in"')
    const events = await collect((onEvent) => runLoginCli(cli, [], {}, onEvent, deviceLink))
    expect(events).toEqual([
      { kind: 'link', url: 'https://accounts.x.ai/oauth2/device?user_code=AB12-CD34', code: 'AB12-CD34' },
      { kind: 'done' }
    ])
  })

  it('reports failure with the last output lines', async () => {
    const cli = script('echo "network unreachable" >&2; exit 2')
    const events = await collect((onEvent) => runLoginCli(cli, [], {}, onEvent, deviceLink))
    expect(events).toEqual([{ kind: 'failed', message: 'network unreachable' }])
  })

  it('reports nothing after cancel', async () => {
    const cli = script('sleep 5')
    const events: SignInEvent[] = []
    const flow = runLoginCli(cli, [], {}, (event) => events.push(event), deviceLink)
    flow.cancel()
    await new Promise((resolve) => setTimeout(resolve, 300))
    expect(events).toEqual([])
  })
})
