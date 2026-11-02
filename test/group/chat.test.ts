import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { beforeEach, describe, expect, it } from 'vitest'
import { GroupChat, GroupChats } from '../../src/group/chat'
import { parseMentions } from '../../src/group/mentions'
import { SessionManager } from '../../src/sessions/manager'
import { SessionStore } from '../../src/sessions/store'
import { FakeSession, fakeProvider } from '../fake-provider'
import { MemoryMemento } from '../memory-memento'

const tick = () => new Promise((resolve) => setTimeout(resolve, 20))
const texts = (session: FakeSession | undefined) => session?.prompts.map((parts) => parts.flatMap((part) => (part.type === 'text' ? part.text : '')).join('\n')) ?? []

let chats: GroupChats
let chat: GroupChat
let claude: FakeSession[]
let codex: FakeSession[]
let grok: FakeSession[]
let dir: string
let memento: MemoryMemento

function rebuild(root: string): void {
  build(root)
}

function build(root?: string): void {
  const providers = [fakeProvider('claude', ['steer']), fakeProvider('codex', ['steer']), fakeProvider('grok')]
  ;[claude, codex, grok] = providers.map((provider) => provider.sessions)
  const map = new Map(providers.map(({ provider }) => [provider.id, provider]))
  let group: GroupChats | undefined
  const manager = new SessionManager({
    providers: map,
    store: new SessionStore(memento),
    journalDir: join(dir, 'journal'),
    cwd: dir,
    env: async () => ({}),
    decorate: (record, parts) => group?.decorate(record, parts) ?? Promise.resolve(parts),
    boundary: async (record) => group?.boundary(record)
  })
  group = new GroupChats({ manager, providers: map, dir: join(dir, 'groups'), ...(root ? { root, checkouts: () => [root] } : {}) })
  chats = group
}

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'agentdeck-group-'))
  memento = new MemoryMemento()
  build()
  chat = chats.create({ lead: 'claude' })
})

function finish(session: FakeSession | undefined, reply: string): Promise<unknown> {
  session?.emit({ kind: 'message', id: `reply-${reply}`, role: 'assistant', text: reply, streaming: false })
  session?.endTurn()
  return tick()
}

describe('parseMentions', () => {
  const agents = ['claude', 'codex', 'grok']
  it('splits on each known agent', () => {
    expect(parseMentions('@codex do this @grok do that', agents)).toEqual([{ target: 'codex', text: 'do this' }, { target: 'grok', text: 'do that' }])
  })
  it('keeps leading text untargeted, and is not case sensitive', () => {
    expect(parseMentions('first @Codex second', agents)).toEqual([{ text: 'first' }, { target: 'codex', text: 'second' }])
  })
  it('leaves emails, packages, and unknown names as text', () => {
    expect(parseMentions('ask me@codex.dev about @types/node and @nobody', agents)).toEqual([{ text: 'ask me@codex.dev about @types/node and @nobody' }])
    expect(parseMentions('see @codex/sdk docs', agents)).toEqual([{ text: 'see @codex/sdk docs' }])
  })
})

describe('GroupChat', () => {
  it('sends to the lead by default, then to whoever was last addressed', async () => {
    await chat.send('hello')
    await tick()
    expect(texts(claude[0])).toEqual(['hello'])
    await finish(claude[0], 'hi')
    await chat.send('@codex build it')
    await tick()
    expect(chat.record.target).toBe('codex')
    await finish(codex[0], 'built')
    await chat.send('and test it')
    await tick()
    expect(codex[0].prompts).toHaveLength(2)
  })

  it('runs one agent at a time, in order', async () => {
    const results = await chat.send('@codex do this @grok do that')
    expect(results.map((result) => [result.target, result.delivery])).toEqual([['codex', 'now'], ['grok', 'queued']])
    await tick()
    expect(codex[0].prompts).toHaveLength(1)
    expect(grok).toHaveLength(0)
    expect(chat.state().running).toBe('codex')
    expect(chat.state().queue.map((message) => message.target)).toEqual(['grok'])
    await finish(codex[0], 'done')
    expect(chat.state().running).toBe('grok')
    expect(grok[0].prompts).toHaveLength(1)
  })

  it('catches an agent up on what it missed, and only that', async () => {
    await chat.send('@codex note the word apple')
    await tick()
    await finish(codex[0], 'noted apple')
    await chat.send('@grok what did codex say')
    await tick()
    expect(texts(grok[0])[0]).toContain('[codex] noted apple')
    expect(texts(grok[0])[0]).toContain('[user to codex] note the word apple')
    expect(texts(grok[0])[0].match(/what did codex say/g)).toHaveLength(1)
    await finish(grok[0], 'it said apple')
    await chat.send('@codex and now')
    await tick()
    const second = texts(codex[0])[1]
    expect(second).toContain('[grok] it said apple')
    expect(second).not.toContain('noted apple')
  })

  it('keeps catch-up out of the transcript the user sees', async () => {
    await chat.send('@codex first')
    await tick()
    await finish(codex[0], 'one')
    await chat.send('@grok second')
    await tick()
    const shown = chat.items().filter(({ item }) => item.kind === 'message' && item.role === 'user')
    expect(JSON.stringify(shown.at(-1))).not.toContain('chat-so-far')
  })

  it('steers a mention into the running agent where the provider can', async () => {
    await chat.send('@codex long task')
    await tick()
    const [result] = await chat.send('@codex use a cursor')
    expect(result.delivery).toBe('now')
    expect(codex[0].steers).toHaveLength(1)
    expect(chat.state().queue).toEqual([])
    expect(chat.ledger.all().at(-1)).toMatchObject({ from: 'user', to: 'codex', text: 'use a cursor' })
  })

  it('delivers at the end of the turn where it cannot, ahead of other agents', async () => {
    await chat.send('@grok long task @codex after')
    await tick()
    const [result] = await chat.send('@grok use a cursor')
    expect(result.delivery).toBe('end-of-turn')
    expect(chat.state().queue.map((message) => message.target)).toEqual(['grok', 'codex'])
    await finish(grok[0], 'done')
    expect(texts(grok[0]).at(-1)).toContain('use a cursor')
    expect(codex).toHaveLength(0)
  })

  it('queues a mention for an agent that is waiting on the user, and for one that has not started', async () => {
    await chat.send('@grok ask something @codex later')
    await tick()
    grok[0].emit({ kind: 'approval', id: 'a1', title: 'Allow?', options: [] } as never)
    await tick()
    expect(chat.state().members.find((member) => member.agent === 'grok')?.status).toBe('needs-input')
    expect((await chat.send('@grok one more thing'))[0].delivery).toBe('queued')
    expect((await chat.send('@codex also'))[0].delivery).toBe('queued')
  })

  it('stops the running agent so a message can go now', async () => {
    await chat.send('@grok long task')
    await tick()
    const [result] = await chat.send('@grok stop that')
    let cancelled = false
    grok[0].cancel = async () => {
      cancelled = true
      grok[0].endTurn()
    }
    await chat.stopAndSend(result.id)
    await tick()
    expect(cancelled).toBe(true)
    expect(texts(grok[0]).at(-1)).toContain('stop that')
  })

  it('lets the user cancel and reorder the queue', async () => {
    await chat.send('@codex a @grok b @claude c')
    await tick()
    const [grokMessage, claudeMessage] = chat.state().queue
    chat.moveQueued(claudeMessage.id, 0)
    expect(chat.state().queue[0].target).toBe('claude')
    chat.cancelQueued(grokMessage.id)
    expect(chat.state().queue.map((message) => message.target)).toEqual(['claude'])
  })

  it('stops the queue on a failed turn until the user retries', async () => {
    await chat.send('@codex fail @grok after')
    await tick()
    codex[0].exit('boom')
    await tick()
    expect(chat.state().blocked).toContain('codex')
    expect(grok).toHaveLength(0)
    chat.retry()
    await tick()
    expect(grok[0].prompts).toHaveLength(1)
  })

  it('switches lead, and puts all agents on the lane', async () => {
    await chat.send('@codex a')
    await tick()
    await chat.setLane('feature')
    chat.setLead('grok')
    expect(chat.state()).toMatchObject({ lead: 'grok', target: 'grok', laneId: 'feature' })
  })

  it('merges every agent into one timeline', async () => {
    await chat.send('@codex a')
    await tick()
    await finish(codex[0], 'one')
    await chat.send('@grok b')
    await tick()
    await finish(grok[0], 'two')
    const order = chat.items().filter(({ item }) => item.kind === 'message').map(({ agent, item }) => `${agent}:${item.kind === 'message' && item.role}`)
    expect(order).toEqual(['codex:user', 'codex:assistant', 'grok:user', 'grok:assistant'])
  })

  it('survives a reload: members, queue, ledger, cursors, and timeline', async () => {
    await chat.send('@codex a @grok b')
    await tick()
    await finish(codex[0], 'one')
    await finish(grok[0], 'two')
    await chat.send('@codex c')
    await tick()
    await finish(codex[0], 'three')
    const { id } = chat.record
    chats.dispose()
    build()
    const again = chats.get(id)
    expect(again?.ledger.length).toBe(6)
    expect(again?.state().members.map((member) => member.agent).sort()).toEqual(['codex', 'grok'])
    await again?.send('@grok next')
    await tick()
    expect(grok[0].options.resumeId).toBeDefined()
    expect(texts(grok[0])[0]).toContain('[codex] three')
    expect(texts(grok[0])[0]).not.toContain('[codex] one')
  })

  it('reports live activity from the stream', async () => {
    await chat.send('@codex a')
    await tick()
    codex[0].emit({ kind: 'tool', id: 't', title: 'Bash pnpm test', toolKind: 'execute', status: 'running' })
    await tick()
    expect(chat.state().members[0].activity).toBe('$ pnpm test')
  })
})

describe('delegation', () => {
  let repo: string
  const git = (...args: string[]) => execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim()
  const lead = () => chats.create({ lead: 'claude', roster: { plan: 'claude', implement: 'codex', review: 'grok' }, verify: 'test -f built.txt' })

  beforeEach(() => {
    repo = mkdtempSync(join(tmpdir(), 'agentdeck-delegate-'))
    git('init', '-q', '-b', 'main')
    git('config', 'user.email', 'x@example.com')
    git('config', 'user.name', 'x')
    writeFileSync(join(repo, 'a.txt'), 'a\n')
    git('add', '.')
    git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'i')
    rebuild(repo)
    chat = lead()
  })

  it('tells the lead the roster on its first turn only, and keeps it out of the transcript', async () => {
    await chat.send('plan it')
    await tick()
    expect(texts(claude[0])[0]).toContain('Roster: plan: claude, implement: codex, review: grok')
    await finish(claude[0], 'planned')
    await chat.send('more')
    await tick()
    expect(texts(claude[0])[1]).not.toContain('Roster:')
  })

  it('runs a delegate only after the lead ends its turn, then wakes the lead with the report and facts', async () => {
    await chat.send('build it')
    await tick()
    expect(chat.handleTool('claude', 'delegate', { to: 'implement', task: 'Make built.txt', doneWhen: 'it exists' })).toContain('Accepted')
    await tick()
    expect(codex).toHaveLength(0)
    await finish(claude[0], 'handing over')
    expect(texts(codex[0])[0]).toContain('Task: Make built.txt')
    expect(texts(codex[0])[0]).toContain('Before each step')
    writeFileSync(join(repo, 'built.txt'), 'x\n')
    codex[0].emit({ kind: 'tool', id: 't1', title: 'Run touch built.txt', toolKind: 'execute', status: 'done' })
    await finish(codex[0], 'Built it.\nSTATUS: done')
    await tick()
    const report = texts(claude[0]).at(-1)
    expect(report).toContain('Report from codex')
    expect(report).toContain('A\tbuilt.txt')
    expect(report).toContain('touch built.txt')
    expect(report).toContain('AgentDeck ran test -f built.txt: passed')
    expect(chat.state().delegations[0]).toMatchObject({ status: 'done' })
    expect(readFileSync(chat.state().delegations[0].handoff ?? '', 'utf8')).toContain('Built it.')
  })

  it('reports what a failed verify really says, whatever the agent claims', async () => {
    await chat.send('build')
    await tick()
    chat.handleTool('claude', 'delegate', { to: 'codex', task: 'Make it' })
    await finish(claude[0], 'ok')
    writeFileSync(join(repo, 'other.txt'), 'x\n')
    await finish(codex[0], 'All good.\nSTATUS: done')
    await tick()
    expect(texts(claude[0]).at(-1)).toContain('FAILED')
  })

  it('shows when an agent ran nothing, and when it gave no status', async () => {
    await chat.send('review')
    await tick()
    chat.handleTool('claude', 'delegate', { to: 'review', task: 'Run the tests' })
    await finish(claude[0], 'ok')
    await finish(grok[0], 'The tests pass.')
    await tick()
    const report = texts(claude[0]).at(-1)
    expect(report).toContain('Commands run: none')
    expect(report).toContain('did not give a status line')
    expect(chat.state().delegations[0].status).toBe('unknown')
  })

  it('refuses delegation from anyone but the lead, to nobody, or to itself', async () => {
    expect(chat.handleTool('codex', 'delegate', { to: 'review', task: 'x' })).toContain('Only the lead')
    expect(chat.handleTool('claude', 'delegate', { to: 'research', task: 'x' })).toContain('Nobody holds')
    expect(chat.handleTool('claude', 'delegate', { to: 'plan', task: 'x' })).toContain('That is you')
  })

  it('reminds a lead once if it says it will delegate but does not', async () => {
    await chat.send('build')
    await tick()
    await finish(claude[0], "I'll hand this off to codex.")
    expect(texts(claude[0]).at(-1)).toContain('no delegate call reached')
    await finish(claude[0], "I'm handing it over.")
    expect(claude[0].prompts).toHaveLength(2)
  })

  it('blocks writes for read-only roles, flags a write that got through, and can undo it', async () => {
    expect(chat.readOnlyBoundary('claude')?.roots).toEqual([])
    expect(await chat.readOnlyBoundary('claude')?.outside('x')).toContain('Delegate this edit to codex')
    expect(chat.readOnlyBoundary('codex')).toBeUndefined()
    await chat.send('look')
    await tick()
    writeFileSync(join(repo, 'sneaky.txt'), 'x\n')
    writeFileSync(join(repo, 'a.txt'), 'changed\n')
    await finish(claude[0], 'done')
    await tick()
    const [violation] = chat.state().violations
    expect(violation.files).toEqual(expect.arrayContaining(['A\tsneaky.txt', 'M\ta.txt']))
    chat.undoViolation(violation.id)
    expect(existsSync(join(repo, 'sneaky.txt'))).toBe(false)
    expect(readFileSync(join(repo, 'a.txt'), 'utf8')).toBe('a\n')
  })

  it('reports a failed delegate without waking the lead, and stops the queue', async () => {
    await chat.send('build')
    await tick()
    chat.handleTool('claude', 'delegate', { to: 'codex', task: 'x' })
    await finish(claude[0], 'ok')
    codex[0].exit('boom')
    await tick()
    expect(chat.state().delegations[0].status).toBe('failed')
    expect(chat.state().blocked).toContain('codex')
  })

  it('lets a mention reach a delegate while it works', async () => {
    await chat.send('build')
    await tick()
    chat.handleTool('claude', 'delegate', { to: 'codex', task: 'x' })
    await finish(claude[0], 'ok')
    expect((await chat.send('@codex use a cursor'))[0].delivery).toBe('now')
    expect(codex[0].steers).toHaveLength(1)
  })
})
