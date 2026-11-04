import { existsSync, readFileSync, utimesSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { LaneMemory, stamp } from '../../src/lanes/memory'
import { parseToml, stringifyToml } from '../../src/lanes/toml'
import { repo, workspace } from './repos'

describe('toml subset', () => {
  it('round-trips keys, strings, numbers, arrays, and tables', () => {
    const data = { name: 'retry-fix', goal: 'Fix "retry"\nfor real', count: 2, files: ['.env', '.env.local'], setup: { command: 'pnpm install' } }
    expect(parseToml(stringifyToml(data))).toEqual(data)
  })

  it('skips comments and lines outside the subset', () => {
    expect(parseToml('# note\nname = "x"\nweird = bare words\n[t]\nk = true\n')).toEqual({ name: 'x', t: { k: true } })
  })
})

describe('LaneMemory', () => {
  it('creates a lane folder with lane.toml, plan.md, notes.md, and chats/', () => {
    const root = workspace()
    const memory = new LaneMemory(root)
    expect(memory.exists('feat/retry')).toBe(false)
    memory.ensure('feat/retry')
    const dir = join(root, '.canopy', 'lanes', 'feat--retry')
    expect(memory.laneDir('feat/retry')).toBe(dir)
    expect(parseToml(readFileSync(join(dir, 'lane.toml'), 'utf8'))).toMatchObject({ name: 'feat/retry' })
    expect(existsSync(join(dir, 'plan.md'))).toBe(true)
    expect(existsSync(join(dir, 'notes.md'))).toBe(true)
    expect(existsSync(join(dir, 'chats'))).toBe(true)
  })

  it('stores the goal', () => {
    const memory = new LaneMemory(workspace())
    expect(memory.goal('x')).toBeUndefined()
    memory.setGoal('x', 'Make retry reliable')
    expect(memory.goal('x')).toBe('Make retry reliable')
  })

  it('reports when the plan changed and how many notes there are', () => {
    const memory = new LaneMemory(workspace())
    memory.ensure('x')
    expect(memory.planUpdated('x')).toBeUndefined()
    writeFileSync(memory.planPath('x'), '1. do it\n')
    const when = new Date('2026-10-29T10:00:00Z')
    utimesSync(memory.planPath('x'), when, when)
    expect(memory.planUpdated('x')).toBe('2026-10-29T10:00:00.000Z')
    writeFileSync(memory.notesPath('x'), '# Notes\n- one\n- two\nnot a note\n')
    expect(memory.noteCount('x')).toBe(2)
  })

  it('lists chat summaries newest first with their titles', () => {
    const memory = new LaneMemory(workspace())
    memory.writeSummary('x', 'a', '<!-- s -->\n# Research · grok\nbody\n')
    memory.writeSummary('x', 'b', '<!-- s -->\n# Plan · claude\nbody\n')
    utimesSync(join(memory.laneDir('x'), 'chats', 'a.md'), new Date(1000), new Date(1000))
    expect(memory.summaries('x').map(({ chatId, title }) => ({ chatId, title }))).toEqual([
      { chatId: 'b', title: 'Plan · claude' },
      { chatId: 'a', title: 'Research · grok' }
    ])
  })

  it('appends history only for lanes it already holds', () => {
    const memory = new LaneMemory(workspace())
    memory.appendHistory('x', { event: 'moved' })
    expect(memory.exists('x')).toBe(false)
    memory.ensure('x')
    memory.appendHistory('x', { event: 'moved', repo: 'api' })
    const lines = readFileSync(join(memory.laneDir('x'), 'history.jsonl'), 'utf8').trim().split('\n')
    expect(JSON.parse(lines[0])).toMatchObject({ event: 'moved', repo: 'api', at: expect.any(String) })
  })

  it('keeps .canopy out of a single-repo workspace, once', () => {
    const root = repo(workspace())
    const memory = new LaneMemory(root)
    memory.ensure('x')
    memory.ensure('y')
    const exclude = readFileSync(join(root, '.git', 'info', 'exclude'), 'utf8')
    expect(exclude.split('\n').filter((line) => line === '.canopy/')).toHaveLength(1)
  })

  it('stamps with time, author, and short commits', () => {
    expect(stamp('claude:1a2b', [{ repo: 'api', head: '3f2c1a0aaaa' }, { repo: 'ui' }], new Date('2026-10-29T15:41:00Z'))).toBe(
      '<!-- 2026-10-29T15:41:00.000Z · claude:1a2b · api@3f2c1a0 -->'
    )
  })
})
