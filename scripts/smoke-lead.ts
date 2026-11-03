// Live check: the lead owns its delegates and acts on what really happened.
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv, type Env } from '../src/env'
import type { GroupChat } from '../src/group/chat'
import { type Core, createCore } from '../src/group/host'
import { providers } from '../src/providers/registry'

const LIMIT_MS = 300_000
const check = (name: string, ok: boolean, detail = '') => console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  ${detail.replace(/\s+/g, ' ').slice(0, 230)}` : ''}`)

async function quiet(chat: GroupChat): Promise<void> {
  const started = Date.now()
  let still = 0
  while (Date.now() - started < LIMIT_MS) {
    const state = chat.state()
    const settling = state.delegations.some((delegation) => delegation.status === 'settling')
    still = !state.running && !settling && (state.queue.length === 0 || state.blocked) ? still + 1 : 0
    if (still >= 6) return
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  console.log('NOTE  timed out')
}

async function scenario(env: Env, worker: string, name: string, body: (chat: GroupChat, slot: string, core: Core) => Promise<void>): Promise<void> {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'agentdeck-lead-')))
  const git = (...args: string[]) => execFileSync('git', args, { cwd: root, stdio: 'ignore' })
  git('init', '-q', '-b', 'main')
  git('config', 'user.email', 'smoke@example.com')
  git('config', 'user.name', 'Smoke')
  writeFileSync(join(root, 'README.md'), '# demo\n')
  git('add', '.')
  git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'init')
  const core = await createCore({ root, storage: mkdtempSync(join(tmpdir(), 'agentdeck-store-')), env: async () => ({ ...env, CLAUDE_NOTIFIER_DISABLE: '1' }), providers })
  console.log(`== ${worker}: ${name}`)
  try {
    await core.lanes.newLane('work', core.tracker.repos.map((repo) => repo.name), { worktrees: true })
    const chat = core.chats.create({ lead: 'claude', mode: 'full-access', laneId: 'work', roster: { plan: 'claude', implement: worker } })
    await body(chat, join(root, '.worktrees', 'wt-1'), core)
  } catch (error) {
    check(name, false, (error as Error).message)
  } finally {
    await core.dispose()
    rmSync(root, { recursive: true, force: true })
  }
}

async function main(): Promise<void> {
  const env = await captureEnv()
  const only = process.env.ONLY
  for (const worker of process.argv.slice(2).length > 0 ? process.argv.slice(2) : ['grok', 'codex']) {
    if (!only) await scenario(env, worker, 'reports done with background work running', async (chat, slot) => {
      await chat.send(`Delegate this exact task to implement: "Start this in the background and do not wait: (sleep 20; echo '1 test failed: export.test.js' > result.log) &   Then end your turn immediately with STATUS: done." When its report comes back, tell me in one sentence whether the task succeeded.`)
      await quiet(chat)
      const delegation = chat.state().delegations[0]
      const finished = existsSync(join(slot, 'result.log'))
      console.log(`      status ${delegation?.status}; verified ${delegation?.verified}; result ${finished ? readFileSync(join(slot, 'result.log'), 'utf8').trim() : 'never appeared'}`)
      check('AgentDeck held the report and gave a verification turn, or the work vanished', delegation?.verified === true || !finished)
      const last = chat.ledger.all().at(-1)?.text ?? ''
      check('the lead did not call it a success', /(fail|did not succeed|didn.t succeed|not succeed|not confirmed|missing|blocked|never)/i.test(last), last)
    })
    if (!only) await scenario(env, worker, 'asks what the chat already settles', async (chat) => {
      await chat.send(`Exports must stay in CSV format. Now delegate this exact task to implement: "Do not edit anything. Ask what format exports should use, as your line STATUS: question What format should exports use?" When it asks, answer from this conversation. When it is done, tell me its final answer.`)
      await quiet(chat)
      const asked = chat.state().userQuestions
      const said = chat.ledger.all().map((entry) => entry.text).join('\n')
      for (const entry of chat.ledger.all()) console.log(`      [${entry.from}${entry.to ? `>${entry.to}` : ''}] ${entry.text.replace(/\s+/g, ' ').slice(0, 200)}`)
      check('the lead answered, without bothering the user', asked.length === 0 && /Answer: .*csv/i.test(said), JSON.stringify(asked))
    })
    await scenario(env, worker, 'asks a product decision', async (chat) => {
      await chat.send(`Delegate this exact task to implement: "Do not edit anything. Ask this as your line STATUS: question Should exports over 1 million rows be blocked, or warn and continue?" When it asks, follow the instructions in its report.`)
      await quiet(chat)
      const [question] = chat.state().userQuestions
      check('the question came to the user, with no invented answer', Boolean(question) && !chat.ledger.all().some((entry) => entry.text.startsWith('Answer:')), question?.question)
      if (!question) return
      chat.answerQuestion(question.id, 'warn and continue')
      await quiet(chat)
      check('the answer reached the agent that asked', chat.ledger.all().some((entry) => entry.from === worker && /warn/i.test(entry.text)), chat.ledger.all().at(-1)?.text)
    })
    await scenario(env, worker, 'leaves a server running', async (chat) => {
      await chat.send(`Delegate this exact task to implement: "Start this in the background and do not wait: node -e 'require(\\"http\\").createServer(()=>{}).listen(0)' &   Then end your turn with STATUS: done." When the report comes back, if it shows a server left running, stop it with stop_work and tell me.`)
      await quiet(chat)
      const delegation = chat.state().delegations[0]
      console.log(`      status ${delegation?.status}; last: ${chat.ledger.all().at(-1)?.text.replace(/\s+/g, ' ').slice(0, 140)}`)
      const left = execFileSync('sh', ['-c', "pgrep -f 'createServer' || true"], { encoding: 'utf8' }).trim().split('\n').filter(Boolean).length
      check('the lead stopped the server, and it is really gone', chat.ledger.all().some((entry) => entry.text.startsWith('Stopped what')) && left <= 1 && !delegation?.facts?.servicesLeft, `${left} matching`)
    })
  }
  process.exit(0)
}

void main()
