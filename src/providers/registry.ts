import type { ProviderDefinition } from '../core/types'
import { claudeProvider } from './claude/provider'
import { codexProvider } from './codex/provider'
import { acpProvider } from './acp/provider'
import { grok } from './acp/agents'

export const providers: ReadonlyMap<string, ProviderDefinition> = new Map(
  [claudeProvider, codexProvider, acpProvider(grok)].map((provider) => [provider.id, provider])
)
