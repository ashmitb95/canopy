import { describe, expect, it } from 'vitest'
import { banner, compose } from '../../src/notify/compose'
import { popupCommand } from '../../src/notify/popup'
import { soundCommand } from '../../src/notify/sound'

describe('compose', () => {
  it('frames the workspace and event, the chat, then the detail', () => {
    expect(compose({ workspace: 'docsum', event: '✅ finished', chat: 'retry-fix · Codex: Fix the retry', detail: ['Edited 2 files · ran 5 commands'] })).toEqual({
      title: 'docsum | ✅ finished',
      body: '• retry-fix · Codex: Fix the retry •\n\nEdited 2 files · ran 5 commands'
    })
  })

  it('shortens a long chat title at a word', () => {
    const { body } = compose({ workspace: 'w', event: 'e', chat: 'word '.repeat(60), detail: ['a', 'b'] })
    expect(body.split('\n')[0].length).toBeLessThanOrEqual(40)
    expect(body.split('\n')[0]).toMatch(/…/)
  })
})

describe('banner', () => {
  const chat = { workspace: 'docsum', lane: 'retry-fix', provider: 'Codex', title: 'Fix the retry' }

  it('describes a finished turn by its work', () => {
    expect(banner(chat, { reason: 'turn-ended', durationMs: 1, edits: 2, commands: 5 })).toEqual({
      event: 'finished',
      title: 'docsum | ✅ finished',
      body: '• retry-fix · Codex: Fix the retry •\n\nEdited 2 files · ran 5 commands'
    })
    expect(banner({ ...chat, lane: undefined }, { reason: 'turn-ended', durationMs: 1, edits: 1, commands: 0 }).body).toBe(
      '• Codex: Fix the retry •\n\nEdited 1 file'
    )
    expect(banner(chat, { reason: 'turn-ended', durationMs: 1, edits: 0, commands: 0 }).body).toBe('• retry-fix · Codex: Fix the retry •\n\nReplied')
  })

  it('shows the approval, the question, or the failure', () => {
    expect(banner(chat, { reason: 'needs-input', prompt: { kind: 'approval', text: 'Allow Codex to run this command?: pnpm db:migrate' } })).toMatchObject({
      event: 'approval',
      title: 'docsum | ❗ needs approval'
    })
    expect(banner(chat, { reason: 'needs-input', prompt: { kind: 'question', text: 'Which TTL?' } })).toMatchObject({
      event: 'question',
      title: 'docsum | ❓ question',
      body: '• retry-fix · Codex: Fix the retry •\n\nWhich TTL?'
    })
    expect(banner(chat, { reason: 'failed', text: 'boom\nstack' })).toMatchObject({ event: 'failed', title: 'docsum | ✖ failed', body: expect.stringMatching(/boom$/) })
  })
})

describe('soundCommand', () => {
  it('plays system sounds per platform with volume where supported', () => {
    expect(soundCommand('darwin', 'Hero', 0.5)).toEqual({ file: 'afplay', args: ['-v', '0.5', '/System/Library/Sounds/Hero.aiff'] })
    expect(soundCommand('linux', 'Hero', 1)).toMatchObject({ shell: expect.stringContaining('complete.oga') })
    expect(soundCommand('win32', 'Hero', 1)).toMatchObject({ shell: expect.stringContaining('powershell') })
  })
})

describe('popupCommand', () => {
  it('uses terminal-notifier when available, else osascript', () => {
    expect(popupCommand('darwin', 'T', 'B', { terminalNotifier: '/opt/homebrew/bin/terminal-notifier', focus: 'code /w' })).toEqual({
      file: '/opt/homebrew/bin/terminal-notifier',
      args: ['-title', 'T', '-message', 'B', '-execute', 'code /w']
    })
    expect(popupCommand('darwin', 'T "x"', 'B', {})).toEqual({ file: 'osascript', args: ['-e', 'display notification "B" with title "T \\"x\\""'] })
    expect(popupCommand('linux', 'T', 'B', {})).toEqual({ file: 'notify-send', args: ['T', 'B'] })
    expect(popupCommand('win32', "T's", 'B', {})).toMatchObject({ shell: expect.stringContaining('powershell') })
  })
})
