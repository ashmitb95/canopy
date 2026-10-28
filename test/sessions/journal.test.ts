import { appendFileSync, mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { Journal } from '../../src/sessions/journal'

const path = () => join(mkdtempSync(join(tmpdir(), 'agentdeck-journal-')), 'sessions', 's.jsonl')
const text = (id: string, value: string): SessionItem => ({ kind: 'message', id, role: 'assistant', text: value, streaming: false })

describe('Journal', () => {
  it('folds upserts in first-seen order', () => {
    const file = path()
    const journal = new Journal(file)
    journal.append(text('a', '1'))
    journal.append(text('b', '1'))
    journal.flush()
    journal.append(text('a', '2'))
    journal.flush()
    expect(Journal.read(file)).toEqual([text('a', '2'), text('b', '1')])
  })

  it('coalesces repeated upserts between flushes', () => {
    const file = path()
    const journal = new Journal(file)
    for (const value of ['H', 'He', 'Hel']) journal.append(text('a', value))
    journal.flush()
    expect(readFileSync(file, 'utf8').trim().split('\n')).toHaveLength(1)
  })

  it('flushes on its own after the delay', async () => {
    const file = path()
    const journal = new Journal(file, 10)
    journal.append(text('a', '1'))
    await new Promise((resolve) => setTimeout(resolve, 40))
    expect(Journal.read(file)).toEqual([text('a', '1')])
  })

  it('ignores a truncated last line', () => {
    const file = path()
    const journal = new Journal(file)
    journal.append(text('a', '1'))
    journal.flush()
    appendFileSync(file, '{"kind":"message","id":"b","ro')
    expect(Journal.read(file)).toEqual([text('a', '1')])
  })

  it('reads a missing journal as empty', () => {
    expect(Journal.read(path())).toEqual([])
  })
})
