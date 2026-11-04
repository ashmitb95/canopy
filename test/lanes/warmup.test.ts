import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { envFilesFor, readConfig, updateConfig } from '../../src/lanes/config'
import { LaneMemory } from '../../src/lanes/memory'
import { matchEnvFiles, warmUp } from '../../src/lanes/warmup'
import { workspace } from './repos'

describe('updateConfig', () => {
  it('changes only the keys given, keeping the rest', () => {
    const root = workspace()
    mkdirSync(join(root, '.canopy'))
    writeFileSync(join(root, '.canopy', 'config.toml'), 'max_slots = 2\n\n[setup]\nui = "npm ci"\n')
    updateConfig(root, { envFiles: ['.env', '.env.local'], setup: { api: 'pnpm install' } })
    expect(readConfig(root)).toEqual({ envFiles: ['.env', '.env.local'], env: {}, setup: { ui: 'npm ci', api: 'pnpm install' }, worktrees: true, maxSlots: 2 })
    updateConfig(root, { setup: { ui: '' } })
    expect(readConfig(root).setup).toEqual({ api: 'pnpm install' })
  })

  it('keeps env files per repo, falling back to the shared list', () => {
    const root = workspace()
    updateConfig(root, { env: { api: ['.env', 'config/*.local'] } })
    const config = readConfig(root)
    expect(envFilesFor(config, 'api')).toEqual(['.env', 'config/*.local'])
    expect(envFilesFor(config, 'ui')).toEqual(['.env*'])
    updateConfig(root, { env: { api: [] } })
    expect(envFilesFor(readConfig(root), 'api')).toEqual(['.env*'])
  })
})

describe('readConfig', () => {
  it('defaults: .env* files, no setup, worktrees on', () => {
    expect(readConfig(workspace())).toEqual({ envFiles: ['.env*'], env: {}, setup: {}, worktrees: true, maxSlots: 4 })
  })

  it('reads env files, setup per repo, and the worktree default', () => {
    const root = workspace()
    mkdirSync(join(root, '.canopy'))
    writeFileSync(
      join(root, '.canopy', 'config.toml'),
      'env_files = [".env", "config/local.json"]\nworktrees = false\n\n[setup]\napi = "pnpm install"\n'
    )
    expect(readConfig(root)).toEqual({ envFiles: ['.env', 'config/local.json'], env: {}, setup: { api: 'pnpm install' }, worktrees: false, maxSlots: 4 })
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
