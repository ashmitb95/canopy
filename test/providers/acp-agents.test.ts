import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { cursor, customAgent, gemini, opencode } from '../../src/providers/acp/agents'
import { buildProviders } from '../../src/providers/registry'
import { workspace } from '../lanes/repos'

describe('ACP agent specs', () => {
  it('start each agent’s ACP server', () => {
    expect([cursor, opencode, gemini].map((spec) => `${spec.command} ${spec.args.join(' ')}`)).toEqual([
      'cursor-agent acp',
      'opencode acp',
      'gemini --acp'
    ])
  })

  it('pick Gemini’s auth method from the environment', () => {
    expect(gemini.authMethod(['oauth-personal', 'gemini-api-key'], { GEMINI_API_KEY: 'k' })).toBe('gemini-api-key')
    expect(gemini.authMethod(['oauth-personal', 'gemini-api-key'], {})).toBe('oauth-personal')
  })

  it('know when each is signed in', () => {
    const home = workspace()
    expect(gemini.signedIn({}, home)).toBe(false)
    mkdirSync(join(home, '.gemini'))
    writeFileSync(join(home, '.gemini', 'oauth_creds.json'), '{}')
    expect(gemini.signedIn({}, home)).toBe(true)
    expect(opencode.signedIn({}, home)).toBe(false)
    mkdirSync(join(home, '.local', 'share', 'opencode'), { recursive: true })
    writeFileSync(join(home, '.local', 'share', 'opencode', 'auth.json'), '{}')
    expect(opencode.signedIn({}, home)).toBe(true)
    expect(cursor.signedIn({ CURSOR_API_KEY: 'k' }, home)).toBe(true)
  })
})

describe('customAgent', () => {
  it('turns a settings entry into a spec, rejecting incomplete or clashing ones', () => {
    expect(customAgent({ id: 'goose', label: 'Goose', command: 'goose', args: ['acp'] })).toMatchObject({
      id: 'goose',
      label: 'Goose',
      command: 'goose',
      args: ['acp'],
      loginArgs: []
    })
    expect(customAgent({ id: 'x', command: 'x' })).toBeUndefined()
    expect(customAgent({ id: 'claude', label: 'Mine', command: 'mine', args: [] })).toBeUndefined()
  })
})

describe('buildProviders', () => {
  it('lists the built-in providers, then custom agents', () => {
    const ids = [...buildProviders([customAgent({ id: 'goose', label: 'Goose', command: 'goose', args: ['acp'] })!]).keys()]
    expect(ids).toEqual(['claude', 'codex', 'grok', 'cursor', 'opencode', 'gemini', 'goose'])
  })
})
