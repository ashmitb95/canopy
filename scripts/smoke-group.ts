// Live check: a small real feature built by mentioning agents, on a lane, through the core.
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv } from '../src/env'
import type { GroupChat } from '../src/group/chat'
import { createCore } from '../src/group/host'
import { rollingLines } from '../src/group/rolling'
import { providers } from '../src/providers/registry'

const LIMIT_MS = 300_000
const check = (name: string, ok: boolean, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  ${detail.replace(/\s+/g, ' ').slice(0, 220)}` : ''}`)
  if (!ok) process.exitCode = 1
}

const idle = (chat: GroupChat) =>
  new Promise<void>((resolve) => {
    const limit = setTimeout(() => {
      console.log('NOTE  timed out waiting for the chat to go idle')
      off.dispose()
      resolve()
    }, LIMIT_MS)
    const test = () => {
      const state = chat.state()
      if (state.running || (state.queue.length > 0 && !state.blocked)) return
      clearTimeout(limit)
      off.dispose()
      resolve()
    }
    const off = chat.onEvent((event) => {
      if (event.type === 'state') test()
    })
    setTimeout(test, 200)
  })

async function main(): Promise<void> {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'agentdeck-group-')))
  const git = (cwd: string, ...args: string[]) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  git(root, 'init', '-q', '-b', 'main')
  git(root, 'config', 'user.email', 'smoke@example.com')
  git(root, 'config', 'user.name', 'Smoke')
  writeFileSync(join(root, 'package.json'), '{ "name": "demo", "type": "module" }\n')
  git(root, 'add', '.')
  git(root, '-c', 'commit.gpgsign=false', 'commit', '-qm', 'init')
  const env = await captureEnv()
  const core = await createCore({ root, storage: mkdtempSync(join(tmpdir(), 'agentdeck-store-')), env: async () => ({ ...env, CLAUDE_NOTIFIER_DISABLE: '1' }), providers })
  await core.lanes.newLane('slugify', ['.'].flatMap(() => core.tracker.repos.map((repo) => repo.name)), { worktrees: true, goal: 'Add a slugify helper' })
  const slot = join(root, '.worktrees', 'wt-1')
  check('lane starts in a slot', git(slot, 'branch', '--show-current') === 'slugify')
  const chat = core.chats.create({ lead: 'claude', mode: 'full-access', laneId: 'slugify' })
  chat.onEvent((event) => {
    if (event.type !== 'item' || event.item.kind !== 'tool' || event.item.status !== 'done') return
    console.log(`      [${event.agent}] ${rollingLines([event.item])[0]?.text ?? ''}`)
  })
  const notes: string[] = []
  const results = await chat.send(`@codex create slugify.js in the lane that exports slugify(text): lowercase, spaces to dashes, and strip anything that is not a letter, number, or dash. Keep it short. Do not write tests. @grok write slugify.test.js with node:test covering spaces, punctuation, and capitals. Do not change slugify.js. Run it with node --test. If a test fails, report it and stop. @claude read what the others did, run node --test, and tell me in two sentences whether the feature works. Do not edit anything.`)
  check('three agents queued in order', results.map((result) => result.target).join() === 'codex,grok,claude', results.map((result) => result.delivery).join())
  await idle(chat)
  if (chat.state().blocked) notes.push(chat.state().blocked ?? '')
  console.log(`state: ${JSON.stringify({ running: chat.state().running, queue: chat.state().queue.length, blocked: chat.state().blocked })}`)
  check('code landed in the lane, not the primary checkout', existsSync(join(slot, 'slugify.js')) && !existsSync(join(root, 'slugify.js')))
  check('tests landed in the lane', existsSync(join(slot, 'slugify.test.js')))
  let passed = false
  try {
    execFileSync('node', ['--test'], { cwd: slot, stdio: 'ignore' })
    passed = true
  } catch {
    passed = false
  }
  check('the tests really pass', passed)
  const ledger = chat.ledger.all()
  check('every agent spoke, in order', ledger.filter((entry) => entry.from !== 'user').map((entry) => entry.from).join() === 'codex,grok,claude', ledger.filter((entry) => entry.from !== 'user').map((entry) => entry.from).join())
  const last = ledger.at(-1)?.text ?? ''
  check('the last agent knew what the others did', /slugify/i.test(last) && /test/i.test(last), last)
  const beforeFollowUp = chat.ledger.length
  await chat.send('Which agent wrote slugify.js and which wrote the tests? One short sentence.')
  await idle(chat)
  const answer = chat.ledger.all().at(-1)?.text ?? ''
  check('a follow-up goes to the last agent, and it can attribute the work', chat.ledger.length > beforeFollowUp && /codex/i.test(answer) && /grok/i.test(answer), answer)
  check('all three share one timeline', new Set(chat.items().map(({ agent }) => agent)).size === 3, `${chat.items().length} items`)
  console.log(`      final slugify.js: ${existsSync(join(slot, 'slugify.js')) ? readFileSync(join(slot, 'slugify.js'), 'utf8').replace(/\n/g, ' ').slice(0, 170) : 'missing'}`)
  await core.dispose()
  rmSync(root, { recursive: true, force: true })
  process.exit(process.exitCode ?? 0)
}

void main()
