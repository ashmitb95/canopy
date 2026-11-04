// Records a real Codex edit turn's app-server notifications as a translator fixture.
// Only item, turn, and token-usage notifications are kept; other frames carry account details.
import { mkdirSync, mkdtempSync, realpathSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv } from '../src/env'
import { spawnGroup, stopGroup } from '../src/process'
import { findCodex } from '../src/providers/codex/locate'
import { RpcPeer } from '../src/providers/rpc'

const OUT = 'test/fixtures/codex/edit-turn.jsonl'
const KEEP = /^(item\/|turn\/(started|completed|plan\/updated)$|thread\/tokenUsage\/updated$)/

async function main(): Promise<void> {
  const env = await captureEnv()
  const cli = findCodex(env)
  if (!cli) throw new Error('codex CLI not found')
  const cwd = realpathSync(mkdtempSync(join(tmpdir(), 'canopy-record-')))
  writeFileSync(join(cwd, 'notes.md'), '# Notes\n\nhello world\n')

  const child = spawnGroup(cli, ['app-server'], { cwd, env, stdio: ['pipe', 'pipe', 'inherit'] })
  const rpc = new RpcPeer(child.stdout!, child.stdin!)
  const lines: string[] = []
  const completed = new Promise<void>((resolve) => {
    rpc.onNotification(({ method, params }) => {
      if (KEEP.test(method)) lines.push(JSON.stringify({ method, params }).replaceAll(cwd, '/work'))
      if (method === 'turn/completed') resolve()
    })
  })
  await rpc.request('initialize', {
    clientInfo: { name: 'canopy', title: 'Canopy', version: '0.0.1' },
    capabilities: { experimentalApi: true, requestAttestation: false }
  })
  rpc.notify('initialized')
  const { thread } = await rpc.request<{ thread: { id: string } }>('thread/start', {
    cwd,
    approvalPolicy: 'never',
    sandbox: 'workspace-write',
    ephemeral: true
  })
  await rpc.request('turn/start', {
    threadId: thread.id,
    input: [{ type: 'text', text: 'In notes.md, replace "hello world" with "goodbye world" using apply_patch. Then reply with one short sentence.', text_elements: [] }]
  })
  await completed
  await stopGroup(child)
  mkdirSync('test/fixtures/codex', { recursive: true })
  writeFileSync(OUT, `${lines.join('\n')}\n`)
  console.log(`wrote ${lines.length} notifications to ${OUT}`)
}

main().catch((error) => {
  console.error('RECORD FAILED:', error)
  process.exit(1)
})
