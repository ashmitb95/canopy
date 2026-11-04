// Live check: a lead hands a real feature out by roster, unprompted, with Canopy recording what really happened.
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv, type Env } from '../src/env'
import type { GroupChat } from '../src/group/chat'
import { createCore } from '../src/group/host'
import { providers } from '../src/providers/registry'

const LIMIT_MS = 420_000
const check = (name: string, ok: boolean, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  ${detail.replace(/\s+/g, ' ').slice(0, 240)}` : ''}`)
  if (!ok) process.exitCode = 1
}

/** Settled means nobody running and nothing queued, across a short wait: reports wake the lead right after a delegate ends. */
async function settled(chat: GroupChat): Promise<void> {
  const started = Date.now()
  let quiet = 0
  while (Date.now() - started < LIMIT_MS) {
    const state = chat.state()
    quiet = !state.running && (state.queue.length === 0 || state.blocked) ? quiet + 1 : 0
    if (quiet >= 4) return
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  console.log('NOTE  timed out')
}

async function run(env: Env, lead: string, implement: string, review: string): Promise<void> {
  const name = `${lead} leads, ${implement} builds, ${review} reviews`
  console.log(`== ${name}`)
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'canopy-delegate-')))
  const git = (cwd: string, ...args: string[]) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  git(root, 'init', '-q', '-b', 'main')
  git(root, 'config', 'user.email', 'smoke@example.com')
  git(root, 'config', 'user.name', 'Smoke')
  writeFileSync(join(root, 'package.json'), '{ "name": "demo", "type": "module" }\n')
  git(root, 'add', '.')
  git(root, '-c', 'commit.gpgsign=false', 'commit', '-qm', 'init')
  const core = await createCore({ root, storage: mkdtempSync(join(tmpdir(), 'canopy-store-')), env: async () => ({ ...env, CLAUDE_NOTIFIER_DISABLE: '1' }), providers })
  try {
    await core.lanes.newLane('slugify', core.tracker.repos.map((repo) => repo.name), { worktrees: true, goal: 'Add a slugify helper' })
    const slot = join(root, '.worktrees', 'wt-1')
    const chat = core.chats.create({ lead, mode: 'full-access', laneId: 'slugify', roster: { plan: lead, implement, review }, verify: 'node --test' })
    await chat.send('Add slugify.js exporting slugify(text): lowercase, spaces to dashes, and strip anything else that is not a letter, number, or dash, plus slugify.test.js using node:test. Then get it reviewed. Keep it small, and tell me the result when review is done.')
    await settled(chat)
    const { delegations, violations, blocked } = chat.state()
    console.log(`      delegations: ${delegations.map((item) => `${item.agent}/${item.role}:${item.status}`).join(', ') || 'none'}; blocked: ${blocked ?? 'no'}`)
    const built = delegations.find((item) => item.agent === implement)
    const reviewed = delegations.find((item) => item.agent === review)
    check('lead delegated the build unprompted', Boolean(built))
    check('code is in the lane, not the primary checkout', existsSync(join(slot, 'slugify.js')) && !existsSync(join(root, 'slugify.js')))
    check('facts recorded the files', Boolean(built?.facts?.files.some((file) => file.includes('slugify'))), built?.facts?.files.join('; '))
    check('Canopy ran verify itself', built?.facts?.verify?.ok === true, built?.facts?.verify?.output.split('\n').slice(-4).join(' '))
    check('lead sent it to review', Boolean(reviewed))
    console.log(`      review ran: ${reviewed?.facts?.commands.map((command) => command.command).join(' | ') || 'no commands'}`)
    check('no role was broken', violations.length === 0, JSON.stringify(violations.map((violation) => [violation.agent, violation.files])))
    const last = chat.ledger.all().at(-1)
    check('the lead had the last word', last?.from === lead, `${last?.text}`)
    console.log(`      handoff saved: ${built?.handoff ? existsSync(built.handoff) : false}; ledger entries: ${chat.ledger.length}`)
  } catch (error) {
    check(name, false, (error as Error).message)
  } finally {
    await core.dispose()
    rmSync(root, { recursive: true, force: true })
  }
}

const ARRANGEMENTS: Record<string, [string, string, string]> = {
  claude: ['claude', 'codex', 'grok'],
  grok: ['grok', 'claude', 'codex'],
  codex: ['codex', 'grok', 'claude']
}

async function main(): Promise<void> {
  const lead = process.argv[2]
  const picked = lead ? ARRANGEMENTS[lead] : undefined
  if (lead && !picked) {
    console.error(`Unknown lead "${lead}". Use one of: ${Object.keys(ARRANGEMENTS).join(', ')}`)
    process.exit(1)
  }
  const env = await captureEnv()
  for (const [nextLead, implement, review] of picked ? [picked] : Object.values(ARRANGEMENTS)) {
    await run(env, nextLead, implement, review)
  }
  process.exit(process.exitCode ?? 0)
}

void main()
