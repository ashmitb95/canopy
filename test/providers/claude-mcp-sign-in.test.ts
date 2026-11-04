import { describe, expect, it } from 'vitest'
import { claudeProvider } from '../../src/providers/claude/provider'

describe('Claude MCP sign-in', () => {
  it('sends claude.ai connectors to the connector settings page', () => {
    expect(claudeProvider.mcpSignIn?.('claude.ai Notion', 'claudeai')).toEqual({
      kind: 'url',
      url: 'https://claude.ai/settings/connectors'
    })
  })

  it('runs Claude for its /mcp flow for other servers', () => {
    expect(claudeProvider.mcpSignIn?.('linear', 'user')).toEqual({
      kind: 'terminal',
      command: 'claude',
      hint: 'In the terminal, run /mcp and choose linear to sign in. Then press Reconnect in Canopy.'
    })
  })
})
