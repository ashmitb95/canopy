import { describe, expect, it } from 'vitest'
import { type SessionRecord, SessionStore } from '../../src/sessions/store'
import { MemoryMemento } from '../memory-memento'

const record = (id: string, updatedAt: string): SessionRecord => ({
  id,
  providerId: 'claude',
  title: id,
  createdAt: updatedAt,
  updatedAt,
  mode: 'ask',
  hasTurns: false,
  facts: {}
})

describe('SessionStore', () => {
  it('lists records newest first', async () => {
    const store = new SessionStore(new MemoryMemento())
    await store.put(record('old', '2026-01-01T00:00:00.000Z'))
    await store.put(record('new', '2026-02-01T00:00:00.000Z'))
    expect(store.list().map((r) => r.id)).toEqual(['new', 'old'])
  })

  it('replaces a record with the same id', async () => {
    const store = new SessionStore(new MemoryMemento())
    await store.put(record('a', '2026-01-01T00:00:00.000Z'))
    await store.put({ ...record('a', '2026-01-01T00:00:00.000Z'), title: 'Renamed' })
    expect(store.list()).toHaveLength(1)
    expect(store.get('a')?.title).toBe('Renamed')
  })

  it('deletes records', async () => {
    const store = new SessionStore(new MemoryMemento())
    await store.put(record('a', '2026-01-01T00:00:00.000Z'))
    await store.delete('a')
    expect(store.get('a')).toBeUndefined()
  })

  it('returns copies', async () => {
    const store = new SessionStore(new MemoryMemento())
    await store.put(record('a', '2026-01-01T00:00:00.000Z'))
    store.get('a')!.title = 'Mutated'
    expect(store.get('a')?.title).toBe('a')
  })
})
