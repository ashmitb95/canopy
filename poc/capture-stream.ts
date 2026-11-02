// Records each provider's real item stream on one task, with timings, for building the rolling view against.
import { execFileSync } from 'node:child_process'
import { mkdtempSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv } from '../src/env'
import { providers } from '../src/providers/registry'

const TASK = 'This project has a bug: the comment in c.ts states the wrong limit. Find the real limit by reading a.ts and b.ts, fix the comment, add a test file check.test.mjs that uses node:assert to check pages equals 30 by computing it from the same numbers, and run it with node. Then reply with what you changed.'

async function record(id: string, outDir: string): Promise<void> {
  const definition = providers.get(id)
  if (!definition) return
  const repo = realpathSync(mkdtempSync(join(tmpdir(), 'poc-stream-')))
  const git = (...args: string[]) => execFileSync('git', args, { cwd: repo })
  git('init', '-q', '-b', 'main')
  git('config', 'user.email', 'poc@example.com')
  git('config', 'user.name', 'POC')
  writeFileSync(join(repo, 'a.ts'), 'export const limit = 10\n')
  writeFileSync(join(repo, 'b.ts'), "import { limit } from './a'\nexport const pages = limit * 3\n")
  writeFileSync(join(repo, 'c.ts'), "// limit is 20\nimport { pages } from './b'\nconsole.log(pages)\n")
  git('add', '.')
  git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'files')
  const session = await definition.open({ env: await captureEnv(), cwd: repo, mode: 'full-access' })
  const events: { t: number; item: unknown }[] = []
  const started = Date.now()
  let finish: () => void = () => {}
  const ended = new Promise<void>((resolve) => (finish = resolve))
  session.onItem((item) => {
    events.push({ t: Date.now() - started, item })
    if (item.kind === 'turn' && item.state === 'ended') finish()
  })
  await session.prompt([{ type: 'text', text: TASK }])
  await Promise.race([ended, new Promise((resolve) => setTimeout(resolve, 240_000))])
  await session.dispose()
  // Temp paths and the home folder say nothing useful and should not leave this machine.
  const clean = JSON.stringify(events).split(repo).join('.').split(realpathSync(tmpdir())).join('/tmp').split(process.env.HOME ?? '\0').join('~')
  writeFileSync(join(outDir, `${id}.json`), clean)
  rmSync(repo, { recursive: true, force: true })
  console.log(`${id}: ${events.length} events, ${Math.round((Date.now() - started) / 1000)}s`)
}

async function main(): Promise<void> {
  const outDir = process.argv[2]
  for (const id of ['claude', 'codex', 'grok']) await record(id, outDir).catch((error: Error) => console.log(`${id}: ERROR ${error.message.slice(0, 200)}`))
  process.exit(0)
}

void main()
