import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { DEFAULT_TASKS, handoffPrompt, readTasks } from '../../src/lanes/tasks'
import { workspace } from './repos'

describe('readTasks', () => {
  it('defaults to Research, Plan, Build, Review', () => {
    expect(readTasks(workspace())).toEqual(DEFAULT_TASKS)
    expect(DEFAULT_TASKS.map((task) => `${task.label}:${task.provider}:${task.mode}`)).toEqual([
      'Research:grok:ask',
      'Plan:claude:plan',
      'Build:codex:accept-edits',
      'Review:claude:ask'
    ])
  })

  it('reads [task.<id>] tables, skipping incomplete ones', () => {
    const root = workspace()
    mkdirSync(join(root, '.agentdeck'))
    writeFileSync(
      join(root, '.agentdeck', 'config.toml'),
      '[task.build]\nlabel = "Build"\nprovider = "claude"\nmode = "auto"\n\n[task.broken]\nlabel = "Broken"\n'
    )
    expect(readTasks(root)).toEqual([{ id: 'build', label: 'Build', provider: 'claude', mode: 'auto' }])
  })
})

describe('handoffPrompt', () => {
  it('points at the previous chat’s summary on a lane', () => {
    expect(
      handoffPrompt({ task: 'Build', lane: 'retry-fix', from: 'Retry approach', summaryPath: '.agentdeck/lanes/retry-fix/chats/a.md' })
    ).toBe(
      'You are taking over lane retry-fix for the Build step. Start from the previous chat “Retry approach” (summary: .agentdeck/lanes/retry-fix/chats/a.md) and the lane plan, then continue.'
    )
  })

  it('quotes the last reply when there is no lane', () => {
    expect(handoffPrompt({ task: 'Review', from: 'Hero copy', reply: 'Changed the headline.\nKept the CTA.' })).toBe(
      'You are taking over from the chat “Hero copy” for the Review step. Its last reply was:\n\n> Changed the headline.\n> Kept the CTA.\n\nContinue from there.'
    )
  })
})
