import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { configFiles } from '../../src/ui/config-files'
import { workspace } from '../lanes/repos'

describe('configFiles', () => {
  it('lists the config files that exist, labelled by provider', () => {
    const home = workspace()
    const root = workspace()
    mkdirSync(join(home, '.claude'))
    writeFileSync(join(home, '.claude', 'settings.json'), '{}')
    mkdirSync(join(home, '.codex'))
    writeFileSync(join(home, '.codex', 'config.toml'), '')
    mkdirSync(join(root, '.agentdeck'))
    writeFileSync(join(root, '.agentdeck', 'config.toml'), '')
    expect(configFiles(home, root)).toEqual([
      { label: 'Claude settings', path: join(home, '.claude', 'settings.json') },
      { label: 'Codex config', path: join(home, '.codex', 'config.toml') },
      { label: 'AgentDeck workspace config', path: join(root, '.agentdeck', 'config.toml') }
    ])
  })
})
