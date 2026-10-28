import type { ProviderDefinition } from '../core/types'
import { claudeProvider } from './claude/provider'
import { codexProvider } from './codex/provider'

export const providers: ReadonlyMap<string, ProviderDefinition> = new Map(
  [claudeProvider, codexProvider].map((provider) => [provider.id, provider])
)
