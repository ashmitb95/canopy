// Live check: Codex, sandboxed to its lane, can commit from a worktree slot.
import { execFileSync } from 'node:child_process'
import { mkdtempSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv } from '../src/env'
import { createCore } from '../src/group/host'
import { providers } from '../src/providers/registry'

async function main(): Promise<void> {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'agentdeck-commit-')))
  const git = (cwd: string, ...args: string[]) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  git(root, 'init', '-q', '-b', 'main')
  git(root, 'config', 'user.email', 'smoke@example.com')
  git(root, 'config', 'user.name', 'Smoke')
  git(root, 'config', 'commit.gpgsign', 'false')
  writeFileSync(join(root, 'a.txt'), 'a\n')
  git(root, 'add', '.')
  git(root, '-c', 'commit.gpgsign=false', 'commit', '-qm', 'init')
  const env = await captureEnv()
  const core = await createCore({ root, storage: mkdtempSync(join(tmpdir(), 'agentdeck-store-')), env: async () => env, providers })
  await core.lanes.newLane('note', core.tracker.repos.map((repo) => repo.name), { worktrees: true })
  const chat = core.chats.create({ lead: 'codex', mode: 'full-access', laneId: 'note', roster: { implement: 'codex' } })
  await chat.send('In the lane worktree, create note.txt containing "hi", then commit it with the message "add note". If git cannot commit from your sandbox, use the commit_work tool from the agentdeck MCP server. Reply with the commit hash.')
  const started = Date.now()
  await new Promise((resolve) => setTimeout(resolve, 2_000))
  while ((chat.state().running || chat.state().queue.length > 0) && Date.now() - started < 180_000) await new Promise((resolve) => setTimeout(resolve, 500))
  const slot = join(root, '.worktrees', 'wt-1')
  const log = git(slot, 'log', '--oneline', '-1')
  console.log(`${log.includes('add note') ? 'PASS' : 'FAIL'}  Codex committed from its slot: ${log}`)
  console.log(`${git(root, 'status', '--short') === '' && git(root, 'log', '-1', '--format=%s') === 'init' ? 'PASS' : 'FAIL'}  the primary checkout is untouched`)
  console.log(`      reply: ${chat.ledger.all().at(-1)?.text.replace(/\s+/g, ' ').slice(0, 160)}`)
  await core.dispose()
  rmSync(root, { recursive: true, force: true })
  process.exit(0)
}

void main()
