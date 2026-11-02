// Proof of concept: a group chat run by the harness. Live checks with real CLIs in temporary repos.
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { ProviderSession, SessionItem, WriteBoundary } from '../src/core/types'
import { captureEnv, type Env } from '../src/env'
import { providers } from '../src/providers/registry'
import { startToolServer, type ToolServer } from './tool-server'

const TURN_MS = 240_000
const git = (cwd: string, args: string[], env?: NodeJS.ProcessEnv) => execFileSync('git', args, { cwd, encoding: 'utf8', env: { ...process.env, ...env } }).trim()

/** Everything in the folder, untracked files included, without touching the working tree, index, or stash list. */
export function snapshotTree(repo: string): string {
  const index = join(realpathSync(tmpdir()), `agentdeck-index-${process.pid}-${Date.now()}`)
  try {
    git(repo, ['add', '-A', '.'], { GIT_INDEX_FILE: index })
    return git(repo, ['write-tree'], { GIT_INDEX_FILE: index })
  } finally {
    rmSync(index, { force: true })
  }
}
const changedFiles = (repo: string, from: string, to: string) => git(repo, ['diff', '--name-status', from, to]).split('\n').filter(Boolean)

type Entry = { from: string; text: string }
type Run = { reply: string; approvals: string[]; questions: SessionItem[]; timedOut: boolean; error?: string }
type Delegation = { provider: string; task: string; doneWhen: string }

const READ_ONLY: WriteBoundary = { roots: [], except: [], outside: async () => 'Your role is read-only here. Do not edit files: delegate the edit, or report what should change.' }

class Group {
  readonly ledger: Entry[] = []
  private readonly sessions = new Map<string, ProviderSession>()
  private readonly cursors = new Map<string, number>()
  readonly nativeIds = new Map<string, string>()
  delegations: Delegation[] = []
  answers: { text: string }[] = []
  escalations: string[] = []
  violations: { provider: string; files: string[] }[] = []
  readonly server: Promise<ToolServer>
  onApproval: (provider: string, item: Extract<SessionItem, { kind: 'approval' }>, session: ProviderSession) => void = (_p, item, session) => session.answer(item.id, { kind: 'option', optionId: 'allow' })

  constructor(
    readonly repo: string,
    private readonly env: Env,
    readonly roster: Record<string, string>,
    readonly writer: string
  ) {
    this.server = startToolServer([
      {
        name: 'delegate',
        description: 'Hands a task to the agent holding a role. It returns immediately. End your turn right after calling it; you get the report on your next turn.',
        inputSchema: { type: 'object', properties: { provider: { type: 'string' }, task: { type: 'string' }, doneWhen: { type: 'string' } }, required: ['provider', 'task'] },
        call: (args) => {
          this.delegations.push({ provider: String(args.provider), task: String(args.task), doneWhen: String(args.doneWhen ?? '') })
          return 'Accepted. End your turn now.'
        }
      },
      {
        name: 'answer_delegate',
        description: 'Answers a question from a delegate, when the conversation already settles it. Cite where.',
        inputSchema: { type: 'object', properties: { answer: { type: 'string' } }, required: ['answer'] },
        call: (args) => {
          this.answers.push({ text: String(args.answer) })
          return 'Sent. End your turn now.'
        }
      },
      {
        name: 'ask_user',
        description: 'Sends a delegate question to the user, when the conversation does not settle it. Never guess at a product decision.',
        inputSchema: { type: 'object', properties: { question: { type: 'string' } }, required: ['question'] },
        call: (args) => {
          this.escalations.push(String(args.question))
          return 'Sent to the user. End your turn now.'
        }
      }
    ])
  }

  private async session(provider: string, resumeId?: string): Promise<ProviderSession> {
    const existing = this.sessions.get(provider)
    if (existing) return existing
    const definition = providers.get(provider)
    if (!definition) throw new Error(`Unknown provider ${provider}`)
    const server = await this.server
    const session = await definition.open({ env: this.env, cwd: this.repo, mode: 'full-access', toolServer: { name: 'agentdeck', url: server.url }, ...(resumeId ? { resumeId } : {}) })
    this.sessions.set(provider, session)
    this.nativeIds.set(provider, session.nativeId)
    return session
  }

  async drop(provider: string): Promise<void> {
    await this.sessions.get(provider)?.dispose()
    this.sessions.delete(provider)
  }

  /** What this agent missed since it last ran. */
  catchUp(provider: string): string {
    const from = this.cursors.get(provider) ?? 0
    const missed = this.ledger.slice(from).filter((entry) => entry.from !== provider)
    return missed.length === 0 ? '' : `<chat-so-far>\n${missed.map((entry) => `[${entry.from}] ${entry.text}`).join('\n')}\n</chat-so-far>\n`
  }

  /** One agent runs at a time, so writes need no locks. Roles are enforced, with `git status` as the backstop. */
  async turn(provider: string, text: string, options: { from?: string; resumeId?: string; keepOpen?: (run: Run) => boolean } = {}): Promise<Run> {
    const session = await this.session(provider, options.resumeId)
    const writes = provider === this.writer
    session.setBoundary?.(writes ? undefined : READ_ONLY)
    const before = snapshotTree(this.repo)
    const run: Run = { reply: '', approvals: [], questions: [], timedOut: false }
    let finish: () => void = () => {}
    const ended = new Promise<void>((resolve) => (finish = resolve))
    const offItem = session.onItem((item) => {
      if (item.kind === 'message' && item.role === 'assistant') run.reply = item.text
      if (item.kind === 'turn' && item.state === 'ended') finish()
      if (item.kind === 'approval' && !item.resolved) {
        run.approvals.push(item.title ?? item.id)
        this.onApproval(provider, item, session)
      }
      if (item.kind === 'question' && !item.resolved && !run.questions.some((seen) => seen.id === item.id)) {
        run.questions.push(item)
        if (options.keepOpen?.(run)) return
      }
    })
    const offExit = session.onExit(({ error }) => {
      run.error = error?.slice(0, 200) ?? 'exited'
      finish()
    })
    const prompt = `${this.catchUp(provider)}${text}`
    if (options.from) this.ledger.push({ from: options.from, text })
    await session.prompt([{ type: 'text', text: prompt }])
    const timer = new Promise<void>((resolve) => setTimeout(() => { run.timedOut = true; resolve() }, TURN_MS))
    await Promise.race([ended, timer])
    offItem.dispose()
    offExit.dispose()
    if (run.reply) this.ledger.push({ from: provider, text: run.reply })
    this.cursors.set(provider, this.ledger.length)
    const after = snapshotTree(this.repo)
    const files = changedFiles(this.repo, before, after)
    if (!writes && files.length > 0) this.violations.push({ provider, files })
    return run
  }

  brief(provider: string): string {
    const others = Object.entries(this.roster).map(([role, agent]) => `${role}: ${agent}`).join(', ')
    return `You are ${provider}, the lead in a group chat of coding agents run by AgentDeck. Roster: ${others}. Only ${this.writer} may edit files; you are read-only unless that is you. When work belongs to another agent, call the delegate tool with that agent's name, without asking the user, then end your turn. Reports reach you on your next turn.`
  }

  /** Runs a delegate and hands the lead its report, with facts recorded by the harness. */
  async runDelegation(lead: string, delegation: Delegation): Promise<{ run: Run; facts: string; files: string[] }> {
    const before = snapshotTree(this.repo)
    const packet = `You are ${delegation.provider}, delegated work by ${lead} in a group chat run by AgentDeck.\nTask: ${delegation.task}\nDone when: ${delegation.doneWhen}\nDo the work, then end your reply with one line: STATUS: done, STATUS: blocked, or STATUS: question, followed by the question if you have one.`
    const run = await this.turn(delegation.provider, packet)
    const files = changedFiles(this.repo, before, snapshotTree(this.repo))
    const facts = `Recorded by AgentDeck, not the delegate. Files changed: ${files.join('; ') || 'none'}.`
    return { run, facts, files }
  }

  async close(): Promise<void> {
    for (const provider of [...this.sessions.keys()]) await this.drop(provider)
    ;(await this.server).close()
  }
}

function tempRepo(): string {
  const dir = realpathSync(mkdtempSync(join(tmpdir(), 'agentdeck-group-')))
  git(dir, ['init', '-q', '-b', 'main'])
  git(dir, ['config', 'user.email', 'poc@example.com'])
  git(dir, ['config', 'user.name', 'POC'])
  writeFileSync(join(dir, 'README.md'), '# poc\n')
  git(dir, ['add', '.'])
  git(dir, ['-c', 'commit.gpgsign=false', 'commit', '-qm', 'init'])
  return dir
}

const code = (prefix: string) => `${prefix}-${Math.random().toString(36).slice(2, 8)}`
const line = (name: string, ok: boolean | string, detail = '') => console.log(`${ok === true ? 'PASS' : ok === false ? 'FAIL' : String(ok)}  ${name}${detail ? `  ${detail.replace(/\s+/g, ' ').slice(0, 220)}` : ''}`)

/** The lead hands implementation to the roster's agent unprompted, and the report wakes it. */
async function delegation(env: Env, lead: string, worker: string): Promise<void> {
  const repo = tempRepo()
  const group = new Group(repo, env, { lead, implement: worker }, worker)
  const word = code('word')
  const name = `${lead} leads ${worker}`
  try {
    const first = await group.turn(lead, `${group.brief(lead)}\nThe user says: create hello.txt containing exactly "${word}".`, { from: 'user' })
    const asked = group.delegations.find((item) => item.provider.toLowerCase() === worker)
    line(`${name}: delegated unprompted, turn ended`, Boolean(asked) && !first.timedOut, asked ? '' : `reply: ${first.reply}`)
    line(`${name}: lead did not write`, !existsSync(join(repo, 'hello.txt')) && group.violations.length === 0, JSON.stringify(group.violations))
    if (!asked) return
    const { run, facts, files } = await group.runDelegation(lead, asked)
    const content = existsSync(join(repo, 'hello.txt')) ? readFileSync(join(repo, 'hello.txt'), 'utf8') : ''
    line(`${name}: delegate wrote the file`, content.includes(word) && files.length > 0, `status line: ${/STATUS:.*/.exec(run.reply)?.[0] ?? 'missing'}`)
    const check = code('facts')
    const woke = await group.turn(lead, `Delegate report from ${worker}:\n${run.reply}\n${facts}\nAudit code ${check}. Tell the user the result in one sentence and include the audit code and which files changed.`)
    line(`${name}: report woke the lead`, woke.reply.includes(check) && woke.reply.includes('hello.txt'), woke.reply)
    line(`${name}: no role violations`, group.violations.length === 0, JSON.stringify(group.violations))
  } catch (error) {
    line(name, false, (error as Error).message)
  } finally {
    await group.close()
    rmSync(repo, { recursive: true, force: true })
  }
}

/** Direct @mentions in turn, with each agent catching up from the ledger. */
async function mentions(env: Env, order: string[]): Promise<void> {
  const repo = tempRepo()
  const group = new Group(repo, env, {}, order[0])
  const name = `mentions ${order.join(' > ')}`
  try {
    const words: string[] = []
    for (const agent of order.slice(0, -1)) {
      const word = code(agent)
      words.push(word)
      await group.turn(agent, `The user says: @${agent} remember that your code word is ${word}. Reply with "noted ${word}" and nothing else.`, { from: 'user' })
    }
    const last = order.at(-1) ?? ''
    const run = await group.turn(last, 'The user says: what code words have the others in this chat given? Reply with only those words.', { from: 'user' })
    line(`${name}: catch-up reached the last agent`, words.every((word) => run.reply.includes(word)), run.reply)
    const back = order[0]
    const later = code('later')
    await group.turn(last, `The user says: the final code word is ${later}. Reply "noted".`, { from: 'user' })
    const again = await group.turn(back, 'The user says: what is the final code word? Reply with only that word.', { from: 'user' })
    line(`${name}: a returning agent gets only what it missed`, again.reply.includes(later), again.reply)
  } catch (error) {
    line(name, false, (error as Error).message)
  } finally {
    await group.close()
    rmSync(repo, { recursive: true, force: true })
  }
}

/** A read-only role: edit tools blocked, and shell writes caught afterwards. */
async function enforcement(env: Env, agent: string): Promise<void> {
  const repo = tempRepo()
  const group = new Group(repo, env, {}, 'someone-else')
  try {
    await group.turn(agent, 'Create edit.txt containing "x" using your file editing tool. If you are refused, say so and stop.')
    line(`${agent} read-only: edit tool blocked`, !existsSync(join(repo, 'edit.txt')), group.violations.length ? JSON.stringify(group.violations) : '')
    group.violations = []
    await group.turn(agent, 'For a sandbox test, run this shell command: echo x > shell.txt. If it is refused, say so and stop.')
    const wrote = existsSync(join(repo, 'shell.txt'))
    line(`${agent} read-only: shell write`, wrote ? (group.violations.length > 0 ? 'CAUGHT' : false) : 'BLOCKED', wrote ? 'write happened, backstop flagged it' : 'write never happened')
  } catch (error) {
    line(`${agent} enforcement`, false, (error as Error).message)
  } finally {
    await group.close()
    rmSync(repo, { recursive: true, force: true })
  }
}

/** Whether a lead answers from the chat, and escalates what the chat does not settle. */
async function questions(env: Env, lead: string, worker: string): Promise<void> {
  const repo = tempRepo()
  const group = new Group(repo, env, { lead, implement: worker }, worker)
  const name = `${lead} answers ${worker}`
  try {
    await group.turn(lead, `${group.brief(lead)}\nThe user says: exports must stay in CSV format. Do not delegate yet: reply "noted".`, { from: 'user' })
    const known = await group.runDelegation(lead, { provider: worker, task: 'Do not edit anything. Your only job is to ask this: what format should exports use? Ask it as your STATUS: question line.', doneWhen: 'You have asked.' })
    line(`${name}: status line found`, /STATUS:\s*question/i.test(known.run.reply), /STATUS:.*/.exec(known.run.reply)?.[0] ?? known.run.reply)
    const rule = 'Use answer_delegate only when the conversation already settles the question, and cite it. Otherwise use ask_user. Never guess at a product decision.'
    await group.turn(lead, `${worker} asks: ${/STATUS:.*/.exec(known.run.reply)?.[0] ?? 'what format should exports use?'}\n${rule}`)
    line(`${name}: answers what the chat settles`, group.answers.some((answer) => /csv/i.test(answer.text)) && group.escalations.length === 0, JSON.stringify(group.answers.at(-1) ?? group.escalations))
    group.answers = []
    group.escalations = []
    await group.turn(lead, `${worker} asks: STATUS: question Should exports over 1 million rows be blocked, or warn and continue?\n${rule}`)
    line(`${name}: escalates a product decision, no invented answer`, group.escalations.length > 0 && group.answers.length === 0, JSON.stringify(group.answers.at(-1) ?? group.escalations))
  } catch (error) {
    line(name, false, (error as Error).message)
  } finally {
    await group.close()
    rmSync(repo, { recursive: true, force: true })
  }
}

/** Approval requests reach the harness, and what happens if the CLI dies with one pending. */
async function permissions(env: Env, agent: string): Promise<void> {
  const repo = tempRepo()
  const definition = providers.get(agent)
  if (!definition) return
  try {
    const session = await definition.open({ env, cwd: repo, mode: 'ask' })
    const seen: string[] = []
    let finish: () => void = () => {}
    let gotApproval: () => void = () => {}
    const asked = new Promise<void>((resolve) => (gotApproval = resolve))
    const ended = new Promise<void>((resolve) => (finish = resolve))
    session.onItem((item) => {
      if (item.kind === 'approval' && !item.resolved) {
        seen.push(item.id)
        gotApproval()
      }
      if (item.kind === 'turn' && item.state === 'ended') finish()
    })
    await session.prompt([{ type: 'text', text: 'Run this shell command: echo approved > permitted.txt' }])
    await Promise.race([asked, ended, new Promise((resolve) => setTimeout(resolve, TURN_MS))])
    line(`${agent} permission: request reached the harness`, seen.length > 0)
    const nativeId = session.nativeId
    await session.dispose()
    line(`${agent} permission: nothing ran while pending`, !existsSync(join(repo, 'permitted.txt')))
    if (seen.length === 0) return
    const resumed = await definition.open({ env, cwd: repo, mode: 'ask', resumeId: nativeId })
    const again: string[] = []
    let finish2: () => void = () => {}
    let got2: () => void = () => {}
    const asked2 = new Promise<void>((resolve) => (got2 = resolve))
    const ended2 = new Promise<void>((resolve) => (finish2 = resolve))
    resumed.onItem((item) => {
      if (item.kind === 'approval' && !item.resolved) {
        again.push(item.id)
        got2()
      }
      if (item.kind === 'turn' && item.state === 'ended') finish2()
    })
    await resumed.prompt([{ type: 'text', text: 'You were restarted while waiting. Please try the same command again.' }])
    await Promise.race([asked2, ended2, new Promise((resolve) => setTimeout(resolve, TURN_MS))])
    line(`${agent} permission: asks again after a restart`, again.length > 0)
    await resumed.dispose()
  } catch (error) {
    line(`${agent} permission`, false, (error as Error).message)
  } finally {
    rmSync(repo, { recursive: true, force: true })
  }
}

/** Snapshots see untracked files, and leave the folder, index, and stash list alone. */
function snapshots(): void {
  const repo = tempRepo()
  writeFileSync(join(repo, 'README.md'), 'staged\n')
  git(repo, ['add', 'README.md'])
  writeFileSync(join(repo, 'untracked.txt'), 'before\n')
  const statusBefore = git(repo, ['status', '--porcelain'])
  const before = snapshotTree(repo)
  line('snapshot: leaves the folder, index, and stash list alone', git(repo, ['status', '--porcelain']) === statusBefore && git(repo, ['stash', 'list']) === '')
  writeFileSync(join(repo, 'untracked.txt'), 'after\n')
  writeFileSync(join(repo, 'new.txt'), 'new\n')
  const files = changedFiles(repo, before, snapshotTree(repo))
  line('snapshot: diff includes untracked files', files.some((file) => file.endsWith('untracked.txt')) && files.some((file) => file.endsWith('new.txt')), files.join('; '))
  rmSync(repo, { recursive: true, force: true })
}

async function main(): Promise<void> {
  const env = await captureEnv()
  const only = process.argv[2]
  const want = (name: string) => !only || only === name
  if (want('snapshots')) snapshots()
  if (want('delegation')) for (const [lead, worker] of [['claude', 'grok'], ['grok', 'codex'], ['codex', 'claude']]) await delegation(env, lead, worker)
  if (want('mentions')) await mentions(env, ['codex', 'grok', 'claude'])
  if (want('enforcement')) for (const agent of ['claude', 'codex', 'grok']) await enforcement(env, agent)
  if (want('questions')) for (const [lead, worker] of [['claude', 'grok'], ['codex', 'claude'], ['grok', 'codex']]) await questions(env, lead, worker)
  if (want('permissions')) for (const agent of ['claude', 'codex', 'grok']) await permissions(env, agent)
  console.log('DONE')
  process.exit(0)
}

void main()
