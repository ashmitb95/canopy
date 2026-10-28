import { chmodSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { grok } from '../../src/providers/acp/agents'
import { findAgentCli } from '../../src/providers/acp/spec'

function executable(path: string): string {
  mkdirSync(join(path, '..'), { recursive: true })
  writeFileSync(path, '#!/bin/sh\n')
  chmodSync(path, 0o755)
  return path
}

describe('ACP agent specs', () => {
  it('finds the CLI on PATH, then in the installer folder', () => {
    const root = mkdtempSync(join(tmpdir(), 'agentdeck-acp-'))
    const installed = executable(join(root, 'home', '.grok', 'bin', 'grok'))
    expect(findAgentCli(grok, { PATH: '' }, join(root, 'home'))).toBe(installed)
    const onPath = executable(join(root, 'bin', 'grok'))
    expect(findAgentCli(grok, { PATH: join(root, 'bin') }, join(root, 'home'))).toBe(onPath)
    expect(findAgentCli(grok, { PATH: '' }, join(root, 'nobody'))).toBeNull()
  })

  it('prefers an API key from the environment, then the cached sign-in', () => {
    expect(grok.authMethod(['cached_token', 'xai.api_key'], { XAI_API_KEY: 'k' })).toBe('xai.api_key')
    expect(grok.authMethod(['cached_token', 'grok.com'], { XAI_API_KEY: 'k' })).toBe('cached_token')
    expect(grok.authMethod(['grok.com'], {})).toBeUndefined()
  })

  it('treats a cached token or an API key as signed in', () => {
    const home = mkdtempSync(join(tmpdir(), 'agentdeck-grok-home-'))
    expect(grok.signedIn({}, home)).toBe(false)
    expect(grok.signedIn({ XAI_API_KEY: 'k' }, home)).toBe(true)
    mkdirSync(join(home, '.grok'))
    writeFileSync(join(home, '.grok', 'auth.json'), '{}')
    expect(grok.signedIn({}, home)).toBe(true)
  })
})
