import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { readConfig } from '../../src/lanes/config'
import { LaneMemory } from '../../src/lanes/memory'
import { matchEnvFiles, warmUp } from '../../src/lanes/warmup'
import { workspace } from './repos'

describe('readConfig', () => {
  it('defaults: .env* files, no setup, worktrees on', () => {
    expect(readConfig(workspace())).toEqual({ envFiles: ['.env*'], setup: {}, worktrees: true })
  })

  it('reads env files, setup per repo, and the worktree default', () => {
    const root = workspace()
    mkdirSync(join(root, '.agentdeck'))
    writeFileSync(
      join(root, '.agentdeck', 'config.toml'),
      'env_files = [".env", "config/local.json"]\nworktrees = false\n\n[setup]\napi = "pnpm install"\n'
    )
    expect(readConfig(root)).toEqual({ envFiles: ['.env', 'config/local.json'], setup: { api: 'pnpm install' }, worktrees: false })
  })
})

describe('lane worktree toggle', () => {
  it('is unset until chosen', () => {
    const memory = new LaneMemory(workspace())
    expect(memory.worktrees('x')).toBeUndefined()
    memory.setWorktrees('x', false)
    expect(memory.worktrees('x')).toBe(false)
  })
})

describe('warmUp', () => {
  it('copies matching env files without overwriting, then runs setup', async () => {
    const main = workspace()
    const target = workspace()
    writeFileSync(join(main, '.env'), 'A=1')
    writeFileSync(join(main, '.env.local'), 'B=2')
    writeFileSync(join(main, 'README.md'), 'x')
    mkdirSync(join(main, 'config'))
    writeFileSync(join(main, 'config', 'local.json'), '{}')
    writeFileSync(join(target, '.env.local'), 'B=mine')
    expect(matchEnvFiles(main, ['.env*', 'config/local.json']).sort()).toEqual(['.env', '.env.local', 'config/local.json'])
    const result = await warmUp(main, target, ['.env*', 'config/local.json'], 'echo ready > setup-ran.txt')
    expect(result.copied.sort()).toEqual(['.env', 'config/local.json'])
    expect(readFileSync(join(target, '.env.local'), 'utf8')).toBe('B=mine')
    expect(readFileSync(join(target, 'config', 'local.json'), 'utf8')).toBe('{}')
    expect(result.setup).toMatchObject({ command: 'echo ready > setup-ran.txt', ok: true })
    expect(readFileSync(join(target, 'setup-ran.txt'), 'utf8').trim()).toBe('ready')
  })

  it('reports a failing setup with the end of its output', async () => {
    const result = await warmUp(workspace(), workspace(), [], 'echo broken >&2; exit 3')
    expect(result.setup).toMatchObject({ ok: false, output: 'broken' })
  })
})
