import { existsSync } from 'node:fs'
import { join } from 'node:path'

/** Provider and AgentDeck config files that exist on this machine, for *Open Provider Config…*. */
export function configFiles(home: string, root: string | undefined): { label: string; path: string }[] {
  const candidates = [
    { label: 'Claude settings', path: join(home, '.claude', 'settings.json') },
    { label: 'Codex config', path: join(home, '.codex', 'config.toml') },
    { label: 'Grok config', path: join(home, '.grok', 'config.toml') },
    { label: 'Gemini settings', path: join(home, '.gemini', 'settings.json') },
    { label: 'OpenCode config', path: join(home, '.config', 'opencode', 'opencode.json') },
    ...(root ? [{ label: 'AgentDeck workspace config', path: join(root, '.agentdeck', 'config.toml') }] : [])
  ]
  return candidates.filter((candidate) => existsSync(candidate.path))
}
