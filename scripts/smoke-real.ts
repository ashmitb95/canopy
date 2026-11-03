// Live check: a real change to AgentDeck itself, built through the core on a clone, verified by the full check.
import { execFileSync } from 'node:child_process'
import { mkdtempSync, realpathSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { captureEnv } from '../src/env'
import { createCore } from '../src/group/host'
import { providers } from '../src/providers/registry'

const TASK =
  'In scripts/driver.ts, add two commands. /review prints each delegation in this chat with its agent, role, status, and the files AgentDeck recorded, numbered. /undo-delegate n undoes the nth delegation with chat.undoDelegation and prints the result. Add both to the HELP text. Keep to the style of the file. Have it built and reviewed, and tell me when it is done.'

async function main(): Promise<void> {
  const source = resolve(process.argv[2] ?? '.')
  const sandbox = realpathSync(mkdtempSync(join(tmpdir(), 'agentdeck-real-')))
  const root = join(sandbox, 'agentdeck')
  execFileSync('git', ['clone', '-q', '--local', '--branch', 'core', source, root])
  execFileSync('git', ['config', 'user.email', 'smoke@example.com'], { cwd: root })
  execFileSync('git', ['config', 'user.name', 'Smoke'], { cwd: root })
  execFileSync('git', ['config', 'commit.gpgsign', 'false'], { cwd: root })
  symlinkSync(join(source, 'node_modules'), join(root, 'node_modules'))
  const env = await captureEnv()
  const core = await createCore({ root, storage: mkdtempSync(join(tmpdir(), 'agentdeck-store-')), env: async () => ({ ...env, CLAUDE_NOTIFIER_DISABLE: '1' }), providers })
  await core.lanes.newLane('driver-review', [core.tracker.repos[0].name], { worktrees: true, goal: 'Review and undo from the driver' })
  const slot = join(root, '.worktrees', 'wt-1')
  symlinkSync(join(source, 'node_modules'), join(slot, 'node_modules'))
  const chat = core.chats.create({ lead: 'claude', mode: 'full-access', laneId: 'driver-review', roster: { plan: 'claude', implement: 'codex', review: 'grok' }, verify: 'pnpm -s typecheck && pnpm -s test' })
  const started = Date.now()
  chat.onEvent((event) => {
    if (event.type === 'state') return
    if (event.item.kind === 'tool' && event.item.status !== 'running') console.log(`      ${Math.round((Date.now() - started) / 1000)}s [${event.agent}] ${event.item.title.split('\n')[0].slice(0, 90)}`)
  })
  await chat.send(TASK)
  let still = 0
  while (Date.now() - started < 1_500_000) {
    const state = chat.state()
    const settling = state.delegations.some((delegation) => delegation.status === 'settling')
    still = !state.running && !settling && (state.queue.length === 0 || state.blocked) ? still + 1 : 0
    if (still >= 6) break
    await new Promise((done) => setTimeout(done, 500))
  }
  const state = chat.state()
  console.log(`delegations: ${state.delegations.map((delegation) => `${delegation.agent}/${delegation.role}:${delegation.status}${delegation.facts?.verify ? ` verify ${delegation.facts.verify.ok ? 'ok' : 'FAILED'}` : ''}`).join(', ')}`)
  console.log(`blocked: ${state.blocked ?? 'no'}; violations: ${state.violations.length}; user questions: ${state.userQuestions.length}`)
  let checks = 'not run'
  try {
    execFileSync('pnpm', ['-s', 'typecheck'], { cwd: slot, stdio: 'ignore' })
    execFileSync('pnpm', ['-s', 'test'], { cwd: slot, stdio: 'ignore' })
    checks = 'pass'
  } catch {
    checks = 'FAIL'
  }
  const diff = execFileSync('git', ['diff', '--stat', 'HEAD'], { cwd: slot, encoding: 'utf8' }) + execFileSync('git', ['log', '--oneline', 'core..HEAD'], { cwd: slot, encoding: 'utf8' })
  console.log(`typecheck and tests in the lane, run here: ${checks}`)
  console.log(`changes:\n${diff.trim()}`)
  console.log(`has /review: ${execFileSync('git', ['grep', '-c', "'/review'", 'HEAD', '--', 'scripts/driver.ts'], { cwd: slot, encoding: 'utf8' }).trim() !== '' ? 'committed' : 'not committed'}; in the working tree: ${execFileSync('grep', ['-c', '/undo-delegate', 'scripts/driver.ts'], { cwd: slot, encoding: 'utf8' }).trim()} mentions`)
  console.log(`lead's last word: ${chat.ledger.all().at(-1)?.text.replace(/\s+/g, ' ').slice(0, 400)}`)
  console.log(`minutes: ${((Date.now() - started) / 60000).toFixed(1)}`)
  await core.dispose()
  rmSync(sandbox, { recursive: true, force: true })
  process.exit(0)
}

void main().catch((error) => {
  console.log(`ERROR ${(error as Error).message}`)
  process.exit(1)
})
