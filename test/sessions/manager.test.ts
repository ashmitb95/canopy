import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { ApprovalItem, PromptPart, SessionItem } from '../../src/core/types'
import { type Attention, type SessionEvent, SessionManager } from '../../src/sessions/manager'
import { SessionStore } from '../../src/sessions/store'
import { fakeProvider } from '../fake-provider'
import { MemoryMemento } from '../memory-memento'

const text = (value: string): PromptPart[] => [{ type: 'text', text: value }]
const settle = () => new Promise((resolve) => setImmediate(resolve))
const approval = (id: string, resolved?: string): ApprovalItem => ({
  kind: 'approval',
  id,
  title: 'Allow Bash?',
  options: [
    { id: 'allow', label: 'Allow once' },
    { id: 'deny', label: 'Deny' }
  ],
  resolved
})

function setup(memento = new MemoryMemento(), journalDir = mkdtempSync(join(tmpdir(), 'agentdeck-manager-'))) {
  const { provider, sessions } = fakeProvider()
  const manager = new SessionManager({
    providers: new Map([[provider.id, provider]]),
    store: new SessionStore(memento),
    journalDir,
    cwd: '/work',
    env: async () => ({ PATH: '/bin' })
  })
  return { manager, sessions, memento, journalDir }
}

function watch(manager: SessionManager, id: string): SessionEvent[] {
  const events: SessionEvent[] = []
  manager.subscribe(id, (event) => events.push(event))
  return events
}

function snapshotItems(manager: SessionManager, id: string): Promise<SessionItem[]> {
  return new Promise((resolve) => {
    const subscription = manager.subscribe(id, (event) => {
      if (event.type !== 'snapshot') return
      resolve(event.items)
      queueMicrotask(() => subscription.dispose())
    })
  })
}

describe('SessionManager', () => {
  it('creates a session and sends a snapshot to subscribers', async () => {
    const { manager } = setup()
    const record = await manager.create('fake')
    const events = watch(manager, record.id)
    expect(events).toEqual([{ type: 'snapshot', record, status: 'idle', items: [], queue: [] }])
    expect(manager.list()).toEqual([{ record, status: 'idle' }])
  })

  it('sends a prompt, titles the session, and returns to idle at turn end', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('Fix the login bug\nmore detail'))
    expect(sessions[0].prompts).toEqual([text('Fix the login bug\nmore detail')])
    expect(sessions[0].options).toMatchObject({ cwd: '/work', mode: 'ask', resumeId: undefined })
    expect(manager.list()[0]).toMatchObject({ record: { title: 'Fix the login bug', hasTurns: true }, status: 'running' })
    sessions[0].endTurn()
    expect(manager.list()[0].status).toBe('idle')
    expect(events.map((event) => event.type)).toEqual(['snapshot', 'status', 'item', 'item', 'status'])
  })

  it('starts the CLI early when warmed and forwards its facts', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.warm(id)
    sessions[0].fact({ kind: 'mcp', servers: [{ name: 'notion', status: 'needs-auth', tools: [] }] })
    expect(events.at(-1)).toEqual({ type: 'fact', fact: { kind: 'mcp', servers: [{ name: 'notion', status: 'needs-auth', tools: [] }] } })
    expect(manager.list()[0].record.facts.mcp).toBeDefined()
    expect(sessions).toHaveLength(1)
  })

  it('starts MCP sign-in through the running session', async () => {
    const { manager } = setup()
    const { id } = await manager.create('fake')
    await manager.warm(id)
    await expect(manager.mcpSignIn(id, 'linear')).resolves.toEqual({ kind: 'url', url: 'https://example.invalid/oauth/linear' })
  })

  it('queues prompts while running and sends them at turn end', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('first'))
    await manager.prompt(id, text('second'))
    expect(sessions[0].prompts).toEqual([text('first')])
    expect(events.at(-1)).toMatchObject({ type: 'queue', queue: [{ parts: text('second') }] })
    sessions[0].endTurn()
    await settle()
    expect(sessions[0].prompts).toEqual([text('first'), text('second')])
    expect(manager.list()[0].status).toBe('running')
  })

  it('removes a queued prompt before it is sent', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('first'))
    await manager.prompt(id, text('second'))
    const queued = events.at(-1) as Extract<SessionEvent, { type: 'queue' }>
    manager.removeQueued(id, queued.queue[0].id)
    sessions[0].endTurn()
    await settle()
    expect(sessions[0].prompts).toEqual([text('first')])
  })

  it('needs input while an approval is pending and forwards the answer', async () => {
    const { manager, sessions } = setup()
    const attention: Attention[] = []
    manager.onAttention((event) => attention.push(event))
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('run it'))
    sessions[0].emit(approval('approval:1'))
    expect(manager.list()[0].status).toBe('needs-input')
    expect(attention).toEqual([{ sessionId: id, reason: 'needs-input', prompt: { kind: 'approval', text: 'Allow Bash?' } }])
    manager.answer(id, 'approval:1', { kind: 'option', optionId: 'allow' })
    expect(sessions[0].answers).toEqual([['approval:1', { kind: 'option', optionId: 'allow' }]])
    sessions[0].emit(approval('approval:1', 'allow'))
    expect(manager.list()[0].status).toBe('running')
  })

  it('reports what a finished turn did, and failures', async () => {
    const { manager, sessions } = setup()
    const attention: Attention[] = []
    manager.onAttention((event) => attention.push(event))
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('go'))
    sessions[0].emit({ kind: 'diff', id: 'd1', path: '/w/a.ts', oldText: 'a', newText: 'b' })
    sessions[0].emit({ kind: 'diff', id: 'd2', path: '/w/a.ts', oldText: 'b', newText: 'c' })
    sessions[0].emit({ kind: 'diff', id: 'd3', path: '/w/b.ts', oldText: null, newText: 'x' })
    sessions[0].emit({ kind: 'tool', id: 't1', title: 'pnpm test', toolKind: 'execute', status: 'done' })
    sessions[0].emit({ kind: 'tool', id: 't2', title: 'read', toolKind: 'read', status: 'done' })
    sessions[0].emit({ kind: 'turn', id: 'turn1', state: 'ended' })
    expect(attention).toEqual([{ sessionId: id, reason: 'turn-ended', durationMs: expect.any(Number), edits: 2, commands: 1 }])
  })

  it('counts only the latest turn', async () => {
    const { manager, sessions } = setup()
    const attention: Attention[] = []
    manager.onAttention((event) => attention.push(event))
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('one'))
    sessions[0].emit({ kind: 'diff', id: 'd1', path: '/w/a.ts', oldText: 'a', newText: 'b' })
    sessions[0].emit({ kind: 'turn', id: 'turn1', state: 'ended' })
    await manager.prompt(id, text('two'))
    sessions[0].emit({ kind: 'turn', id: 'turn2', state: 'ended' })
    expect(attention[1]).toMatchObject({ reason: 'turn-ended', edits: 0, commands: 0 })
  })

  it('says which question is waiting', async () => {
    const { manager, sessions } = setup()
    const attention: Attention[] = []
    manager.onAttention((event) => attention.push(event))
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('ask'))
    sessions[0].emit({
      kind: 'question',
      id: 'question:1',
      questions: [{ id: 'q1', question: 'Which color?', multiSelect: false, allowOther: true, options: [] }]
    })
    expect(attention).toEqual([{ sessionId: id, reason: 'needs-input', prompt: { kind: 'question', text: 'Which color?' } }])
  })

  it('needs input while a question is pending and resumes once it is answered', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('ask me'))
    const question: SessionItem = {
      kind: 'question',
      id: 'question:1',
      questions: [{ id: 'q1', question: 'Which color?', multiSelect: false, allowOther: true, options: [{ id: 'o1', label: 'Red' }] }]
    }
    sessions[0].emit(question)
    expect(manager.list()[0].status).toBe('needs-input')
    sessions[0].emit({ ...question, resolved: { answers: [{ questionId: 'q1', optionIds: ['o1'] }] } } as SessionItem)
    expect(manager.list()[0].status).toBe('running')
  })

  it('records the permission mode a provider switches to', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.warm(id)
    sessions[0].fact({ kind: 'mode', current: 'accept-edits', available: ['ask', 'accept-edits'] })
    expect(manager.list()[0].record.mode).toBe('accept-edits')
  })

  it('fans out to every subscriber until one unsubscribes', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const first: SessionEvent[] = []
    const second: SessionEvent[] = []
    manager.subscribe(id, (event) => first.push(event))
    const subscription = manager.subscribe(id, (event) => second.push(event))
    await manager.warm(id)
    sessions[0].emit({ kind: 'notice', id: 'n1', level: 'info', text: 'one' })
    subscription.dispose()
    sessions[0].emit({ kind: 'notice', id: 'n2', level: 'info', text: 'two' })
    expect(first.filter((event) => event.type === 'item')).toHaveLength(2)
    expect(second.filter((event) => event.type === 'item')).toHaveLength(1)
  })

  it('restores history and resumes the native session after a restart', async () => {
    const before = setup()
    const { id } = await before.manager.create('fake')
    await before.manager.prompt(id, text('remember this'))
    before.sessions[0].emit({ kind: 'message', id: 'a1', role: 'assistant', text: 'ok', streaming: false })
    before.sessions[0].endTurn()
    await before.manager.dispose()

    const after = setup(before.memento, before.journalDir)
    const events = watch(after.manager, id)
    const snapshot = events[0] as Extract<SessionEvent, { type: 'snapshot' }>
    expect(snapshot.items.map((item) => item.kind)).toEqual(['message', 'message', 'turn'])
    await after.manager.prompt(id, text('what did I say?'))
    expect(after.sessions[0].options.resumeId).toBe('native-1')
  })

  it('reports a provider crash and reconnects on the next prompt', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('go'))
    sessions[0].emit({ kind: 'message', id: 'a1', role: 'assistant', text: 'working', streaming: true })
    sessions[0].exit('claude exited with code 1')
    expect(manager.list()[0].status).toBe('error')
    expect(events.at(-2)).toMatchObject({
      type: 'item',
      item: { kind: 'notice', level: 'error', text: 'claude exited with code 1', action: 'retry' }
    })
    await manager.prompt(id, text('again'))
    expect(sessions).toHaveLength(2)
    expect(sessions[1].options.resumeId).toBe('native-1')
  })

  it('starts a fresh native session when resuming fails before any output', async () => {
    const before = setup()
    const { id } = await before.manager.create('fake')
    await before.manager.prompt(id, text('hello'))
    before.sessions[0].endTurn()
    await before.manager.dispose()

    const after = setup(before.memento, before.journalDir)
    await after.manager.prompt(id, text('continue'))
    after.sessions[0].exit('No conversation found with session ID: native-1')
    expect(after.manager.list()[0].record.hasTurns).toBe(false)
    await after.manager.prompt(id, text('continue'))
    expect(after.sessions[1].options.resumeId).toBeUndefined()
  })

  it('switches mode on the record and the running session', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.warm(id)
    await manager.setMode(id, 'accept-edits')
    expect(sessions[0].modes).toEqual(['accept-edits'])
    expect(manager.list()[0].record.mode).toBe('accept-edits')
  })

  it('expires approvals and finishes streams left over from a previous run', async () => {
    const { manager, journalDir, memento } = setup()
    const { id } = await manager.create('fake')
    writeFileSync(
      join(journalDir, `${id}.jsonl`),
      [
        JSON.stringify(approval('approval:old')),
        JSON.stringify({ kind: 'question', id: 'question:old', questions: [] }),
        JSON.stringify({ kind: 'message', id: 'a1', role: 'assistant', text: 'par', streaming: true })
      ].join('\n') + '\n'
    )
    const fresh = setup(memento, journalDir)
    const snapshot = watch(fresh.manager, id)[0] as Extract<SessionEvent, { type: 'snapshot' }>
    expect(snapshot.items).toEqual([
      { ...approval('approval:old'), resolved: 'expired' },
      { kind: 'question', id: 'question:old', questions: [], resolved: 'expired' },
      { kind: 'message', id: 'a1', role: 'assistant', text: 'par', streaming: false }
    ])
  })

  it('stops and deletes a session', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.warm(id)
    await manager.stop(id)
    expect(sessions[0].disposed).toBe(true)
    expect(manager.list()[0].status).toBe('stopped')
    await manager.delete(id)
    expect(manager.list()).toEqual([])
  })

  it('looks up an item by id', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.warm(id)
    sessions[0].emit({ kind: 'notice', id: 'n1', level: 'info', text: 'hello' })
    expect(manager.item(id, 'n1')).toMatchObject({ text: 'hello' })
    expect(manager.item(id, 'missing')).toBeUndefined()
  })

  it('relays quota with the provider id', async () => {
    const { manager, sessions } = setup()
    const seen: unknown[] = []
    manager.onQuota((event) => seen.push(event))
    const { id } = await manager.create('fake')
    await manager.warm(id)
    const quota = { observedAt: 't', windows: [{ label: '5-hour', usedPercent: 40, status: 'ok' as const }] }
    sessions[0].quota(quota)
    expect(seen).toEqual([{ providerId: 'fake', quota }])
  })

  it('stamps when a turn ended', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('go'))
    sessions[0].endTurn()
    const ended = events.find((event) => event.type === 'item' && event.item.kind === 'turn')
    expect(ended).toMatchObject({ item: { state: 'ended', at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T/) } })
  })

  it('puts a chat on a lane and takes it off again', async () => {
    const { manager } = setup()
    const { id } = await manager.create('fake')
    let changes = 0
    manager.onDidChange(() => changes++)
    await manager.setLane(id, 'retry-fix')
    expect(manager.list()[0].record.laneId).toBe('retry-fix')
    await manager.setLane(id, undefined)
    expect(manager.list()[0].record.laneId).toBeUndefined()
    expect(changes).toBe(2)
  })

  it('lists the files a chat edited', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('edit'))
    sessions[0].emit({ kind: 'diff', id: 'd1', path: '/w/a.ts', oldText: 'a', newText: 'b' })
    sessions[0].emit({ kind: 'diff', id: 'd2', path: '/w/b.ts', oldText: null, newText: 'c' })
    expect(manager.diffPaths(id)).toEqual(['/w/a.ts', '/w/b.ts'])
  })

  it('lets a decorator add to what the provider receives while the transcript keeps what the user wrote', async () => {
    const { provider, sessions } = fakeProvider()
    const manager = new SessionManager({
      providers: new Map([[provider.id, provider]]),
      store: new SessionStore(new MemoryMemento()),
      journalDir: mkdtempSync(join(tmpdir(), 'agentdeck-manager-')),
      cwd: '/work',
      env: async () => ({ PATH: '/bin' }),
      decorate: async (record, parts) => {
        record.laneSeen = { lane: 'x', at: 'now', repos: {} }
        return [...parts, { type: 'text', text: '<lane name="x" />' }]
      }
    })
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('hello'))
    expect(sessions[0].prompts[0]).toEqual([...text('hello'), { type: 'text', text: '<lane name="x" />' }])
    expect(events.find((event) => event.type === 'item' && event.item.kind === 'message')).toMatchObject({
      item: { role: 'user', parts: text('hello') }
    })
    expect(manager.list()[0].record.laneSeen).toEqual({ lane: 'x', at: 'now', repos: {} })
  })

  it('knows the last reply and forgets what a chat saw when it changes lane', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('hi'))
    sessions[0].emit({ kind: 'message', id: 'm1', role: 'assistant', text: 'first', streaming: false })
    sessions[0].emit({ kind: 'message', id: 'm2', role: 'assistant', text: 'second', streaming: false })
    expect(manager.lastReply(id)).toBe('second')
    await manager.setLane(id, 'a')
    const record = manager.list()[0].record
    record.laneSeen = { lane: 'a', at: 'now', repos: {} }
    await manager.setLane(id, 'b')
    expect(manager.list()[0].record.laneSeen).toBeUndefined()
  })

  it('lets one chat per lane run; the other waits and goes when the first ends', async () => {
    const { manager, sessions } = setup()
    const first = await manager.create('fake')
    const second = await manager.create('fake')
    await manager.setLane(first.id, 'x')
    await manager.setLane(second.id, 'x')
    await manager.prompt(first.id, text('one'))
    const events = watch(manager, second.id)
    await manager.prompt(second.id, text('two'))
    expect(manager.busyOn(['x']).map((record) => record.id)).toEqual([first.id])
    expect(events.some((event) => event.type === 'item' && event.item.kind === 'notice' && /x is busy/.test(event.item.text))).toBe(true)
    expect(sessions.length).toBe(1)
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'ended' })
    await settle()
    await settle()
    expect(sessions[1].prompts).toEqual([text('two')])
  })

  it('passes the boundary to the provider before each prompt', async () => {
    const { provider, sessions } = fakeProvider()
    const boundary = { roots: ['/w/api'], except: [], outside: async () => 'no' }
    const manager = new SessionManager({
      providers: new Map([[provider.id, provider]]),
      store: new SessionStore(new MemoryMemento()),
      journalDir: mkdtempSync(join(tmpdir(), 'agentdeck-manager-')),
      cwd: '/work',
      env: async () => ({ PATH: '/bin' }),
      boundary: async (record) => (record.laneId ? boundary : undefined)
    })
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('a'))
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'ended' })
    await manager.setLane(id, 'x')
    await manager.prompt(id, text('b'))
    expect(sessions[0].boundaries).toEqual([undefined, boundary])
  })

  it('posts notices into a chat', async () => {
    const { manager } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    manager.notify(id, 'moved')
    expect(events).toContainEqual({ type: 'item', item: { kind: 'notice', id: expect.any(String), level: 'info', text: 'moved' } })
  })

  it('sets the effort live and opens later sessions with it', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.warm(id)
    await manager.setEffort(id, 'high')
    expect(sessions[0].efforts).toEqual(['high'])
    expect(manager.list()[0].record.effort).toBe('high')
    await manager.stop(id)
    await manager.warm(id)
    expect(sessions[1].options.effort).toBe('high')
  })

  it('merges further typing into the last queued message', async () => {
    const { manager } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('first'))
    await manager.prompt(id, text('second'))
    await manager.prompt(id, text('third'))
    const queues = events.filter((event) => event.type === 'queue')
    expect(queues.at(-1)).toMatchObject({ queue: [{ parts: [...text('second'), ...text('third')] }] })
  })

  it('steers a queued message into the running turn', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('first'))
    await manager.prompt(id, text('also this'))
    const queued = events.filter((event) => event.type === 'queue').at(-1)
    const queuedId = queued?.type === 'queue' ? queued.queue[0].id : ''
    await manager.steer(id, queuedId)
    expect(sessions[0].steers).toEqual([text('also this')])
    expect(events.filter((event) => event.type === 'queue').at(-1)).toMatchObject({ queue: [] })
    expect(events.filter((event) => event.type === 'item' && event.item.kind === 'message' && event.item.role === 'user')).toHaveLength(2)
  })

  it('compacts through the provider and notes it in the transcript', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.warm(id)
    const events = watch(manager, id)
    await manager.compact(id)
    expect(sessions[0].compacted).toBe(1)
    expect(events.some((event) => event.type === 'item' && event.item.kind === 'notice' && /Compacting/.test(event.item.text))).toBe(true)
  })

  it('forks a chat into a new one with the same transcript that resumes the forked native session', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.setLane(id, 'x')
    await manager.prompt(id, text('hello'))
    sessions[0].emit({ kind: 'message', id: 'm1', role: 'assistant', text: 'hi', streaming: false })
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'ended' })
    const fork = await manager.fork(id)
    expect(fork).toMatchObject({ title: expect.stringMatching(/\(fork\)$/), hasTurns: true, laneId: 'x', nativeId: `${sessions[0].nativeId}-fork` })
    expect(fork.id).not.toBe(id)
    await manager.warm(fork.id)
    expect(sessions[1].options.resumeId).toBe(`${sessions[0].nativeId}-fork`)
    const snapshot = await new Promise<unknown>((resolve) => manager.subscribe(fork.id, (event) => event.type === 'snapshot' && resolve(event)))
    expect(snapshot).toMatchObject({ items: expect.arrayContaining([expect.objectContaining({ id: 'm1' })]) })
  })

  it('refuses to fork a chat with no turns yet', async () => {
    const { manager } = setup()
    const { id } = await manager.create('fake')
    await expect(manager.fork(id)).rejects.toThrow(/Send a message first/)
  })

  it('rewinds to before a user message: provider, transcript, and journal', async () => {
    const { manager, sessions, memento, journalDir } = setup()
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('first'))
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'started', promptRef: 'p1' })
    sessions[0].emit({ kind: 'message', id: 'a1', role: 'assistant', text: 'one', streaming: false })
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'ended', promptRef: 'p1', ref: 'r1' })
    await manager.prompt(id, text('second'))
    sessions[0].emit({ kind: 'turn', id: 't2', state: 'started', promptRef: 'p2' })
    sessions[0].emit({ kind: 'turn', id: 't2', state: 'ended', promptRef: 'p2', ref: 'r2' })
    const second = (await snapshotItems(manager, id)).find((item) => item.kind === 'message' && item.role === 'user' && item.parts[0]?.type === 'text' && item.parts[0].text === 'second')
    const parts = await manager.rewind(id, second?.id ?? '', false)
    expect(parts).toEqual(text('second'))
    expect(sessions[0].rewinds).toEqual([{ prompt: 'p2', keep: 'r1', files: false }])
    expect((await snapshotItems(manager, id)).map((item) => item.id)).toEqual(expect.arrayContaining(['a1']))
    expect((await snapshotItems(manager, id)).some((item) => item.id === 't2')).toBe(false)
    const reloaded = setup(memento, journalDir).manager
    expect((await snapshotItems(reloaded, id)).some((item) => item.id === 't2')).toBe(false)
  })

  it('restarts the provider at the kept turn when it asks to', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('first'))
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'started', promptRef: 'p1' })
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'ended', promptRef: 'p1', ref: 'r1' })
    await manager.prompt(id, text('second'))
    sessions[0].emit({ kind: 'turn', id: 't2', state: 'started', promptRef: 'p2' })
    sessions[0].emit({ kind: 'turn', id: 't2', state: 'ended', promptRef: 'p2', ref: 'r2' })
    sessions[0].restartOnRewind = true
    const second = (await snapshotItems(manager, id)).filter((item) => item.kind === 'message' && item.role === 'user')[1]
    await manager.rewind(id, second.id, false)
    expect(sessions[0].disposed).toBe(true)
    await manager.warm(id)
    expect(sessions[1].options).toMatchObject({ resumeAt: 'r1' })
    expect(manager.list()[0].record.resumeAt).toBeUndefined()
  })

  it('rewinding the first message starts the provider afresh', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('only'))
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'started', promptRef: 'p1' })
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'ended', promptRef: 'p1', ref: 'r1' })
    sessions[0].restartOnRewind = true
    const first = (await snapshotItems(manager, id)).find((item) => item.kind === 'message' && item.role === 'user')
    await manager.rewind(id, first?.id ?? '', false)
    expect(manager.list()[0].record.hasTurns).toBe(false)
    await manager.warm(id)
    expect(sessions[1].options.resumeId).toBeUndefined()
  })
})
