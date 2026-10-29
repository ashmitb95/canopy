import type { ProviderDefinition } from '../core/types'
import { cursor, gemini, grok, opencode } from './acp/agents'
import { acpProvider } from './acp/provider'
import type { AcpAgentSpec } from './acp/spec'
import { claudeProvider } from './claude/provider'
import { codexProvider } from './codex/provider'

/** Built-in providers, then any ACP agents the user added in settings. */
export function buildProviders(custom: AcpAgentSpec[] = []): ReadonlyMap<string, ProviderDefinition> {
  return new Map(
    [claudeProvider, codexProvider, ...[grok, cursor, opencode, gemini, ...custom].map(acpProvider)].map((provider) => [provider.id, provider])
  )
}

export const providers = buildProviders()
