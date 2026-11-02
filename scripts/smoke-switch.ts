// Live check, no agents: lanes move in a real clone while a dev server runs from the primary checkout.
import { execFileSync, spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { commit, newLane, park, preflight, swap, worktrees } from '../src/lanes/switch'

const sandbox = realpathSync(mkdtempSync(join(tmpdir(), 'agentdeck-switch-')))
const repo = join(sandbox, 'project')
const git = (cwd: string, ...args: string[]) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
const check = (name: string, ok: boolean, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  ${detail}` : ''}`)
  if (!ok) process.exitCode = 1
}

async function fetchStatus(port: number): Promise<number> {
  const response = await fetch(`http://127.0.0.1:${port}/`).catch(() => undefined)
  return response?.status ?? 0
}

async function main(): Promise<void> {
  execFileSync('git', ['clone', '-q', '--local', resolve(process.argv[2] ?? '.'), repo])
  git(repo, 'config', 'user.email', 'smoke@example.com')
  git(repo, 'config', 'user.name', 'Smoke')
  git(repo, 'config', 'commit.gpgsign', 'false')
  const base = git(repo, 'branch', '--show-current')
  mkdirSync(join(repo, 'node_modules'), { recursive: true })
  writeFileSync(join(repo, '.env'), 'SECRET=1\n')
  writeFileSync(join(repo, '.git/info/exclude'), '.env\nnode_modules/\n')

  git(repo, 'switch', '-qc', 'lane-a')
  writeFileSync(join(repo, 'lane-a.txt'), 'a\n')
  git(repo, 'add', '.')
  git(repo, 'commit', '-qm', 'a')
  const server = spawn('node', ['-e', 'const s=require("http").createServer((q,r)=>r.end("ok"));s.listen(0,"127.0.0.1",()=>console.log(s.address().port))'], { cwd: repo, stdio: ['ignore', 'pipe', 'ignore'] })
  const port = await new Promise<number>((done) => server.stdout.once('data', (data) => done(Number(String(data).trim()))))
  check('dev server runs from the primary checkout', (await fetchStatus(port)) === 200, `port ${port}`)

  const slot = (await newLane(repo, 'lane-b', { base })).path
  writeFileSync(join(slot, 'lane-b.txt'), 'b\n')
  writeFileSync(join(repo, 'README.md'), 'edited on lane a\n')
  writeFileSync(join(repo, 'wip-a.txt'), 'untracked on a\n')

  const started = Date.now()
  const moved = await swap(repo, 'lane-b', { base })
  await commit(repo)
  const elapsed = Date.now() - started
  check('lane-b reached the primary checkout', git(repo, 'branch', '--show-current') === 'lane-b', `${elapsed}ms in a repo of ${git(repo, 'ls-files').split('\n').length} files`)
  check('it kept its uncommitted work', readFileSync(join(repo, 'lane-b.txt'), 'utf8') === 'b\n')
  check('lane-a kept its work, in the same slot', moved.slotPath === slot && readFileSync(join(slot, 'README.md'), 'utf8') === 'edited on lane a\n' && readFileSync(join(slot, 'wip-a.txt'), 'utf8') === 'untracked on a\n')
  check('the dev server kept running', (await fetchStatus(port)) === 200)
  check('env files stayed in the primary checkout', readFileSync(join(repo, '.env'), 'utf8') === 'SECRET=1\n')

  writeFileSync(join(slot, 'pnpm-lock.yaml'), 'changed\n')
  git(slot, 'add', 'pnpm-lock.yaml')
  git(slot, 'commit', '-qm', 'deps')
  const back = await swap(repo, 'lane-a', { base })
  await commit(repo)
  check('switching back reports setup only where dependencies changed', back.setupNeeded.includes(repo), back.setupNeeded.map((path) => path.replace(sandbox, '')).join(', '))
  check('work survived the round trip', readFileSync(join(repo, 'README.md'), 'utf8') === 'edited on lane a\n' && readFileSync(join(slot, 'lane-b.txt'), 'utf8') === 'b\n')

  git(slot, 'add', '.')
  git(slot, 'commit', '-qm', 'b work')
  await park(repo, 'lane-b')
  const reused = await newLane(repo, 'lane-c', { base })
  check('a parked slot is reused for a new lane', reused.reused && reused.path === slot, `setup needed: ${reused.setupNeeded}`)
  check('the parked lane is cold, with its branch kept', git(repo, 'branch', '--list', 'lane-b') !== '' && (await preflight(repo, 'lane-b', { base })).kind !== 'stop')
  console.log(`worktrees: ${(await worktrees(repo)).map((tree) => `${tree.path.replace(sandbox, '')}=${tree.branch ?? 'detached'}`).join(' ')}`)
  server.kill()
  rmSync(sandbox, { recursive: true, force: true })
}

void main()
