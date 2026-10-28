// Records a real Grok edit turn as a translator fixture.
// Keeps only session/update content and the stop reason: Grok's other notifications carry
// account details and MCP server environments (including API keys).
import { mkdirSync, mkdtempSync, realpathSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv } from '../src/env'
import { spawnGroup, stopGroup } from '../src/process'
import { grok } from '../src/providers/acp/agents'
import { findAgentCli } from '../src/providers/acp/spec'
import { RpcPeer } from '../src/providers/rpc'

const OUT = 'test/fixtures/grok/edit-turn.jsonl'
const KEEP = new Set(['agent_message_chunk', 'agent_thought_chunk', 'tool_call', 'tool_call_update', 'plan'])

async function main(): Promise<void> {
  const env = await captureEnv()
  const cli = findAgentCli(grok, env, env.HOME ?? homedir())
  if (!cli) throw new Error('grok CLI not found')
  const cwd = realpathSync(mkdtempSync(join(tmpdir(), 'agentdeck-record-')))
  writeFileSync(join(cwd, 'notes.md'), '# Notes\n\nhello world\n')

  const child = spawnGroup(cli, grok.args, { cwd, env, stdio: ['pipe', 'pipe', 'inherit'] })
  const rpc = new RpcPeer(child.stdout!, child.stdin!, { envelope: { jsonrpc: '2.0' } })
  const lines: string[] = []
  rpc.onNotification(({ method, params }) => {
    if (method !== 'session/update') return
    const update = { ...(params as { update: Record<string, unknown> }).update }
    if (!KEEP.has(String(update.sessionUpdate))) return
    delete update.rawOutput
    lines.push(JSON.stringify({ update }).replaceAll(cwd, '/work'))
  })
  rpc.onRequest(async ({ method, params }) => {
    if (method !== 'session/request_permission') throw new Error(`unsupported: ${method}`)
    const { options } = params as { options: { optionId: string; kind: string }[] }
    const allow = options.find((option) => option.kind === 'allow_once') ?? options[0]
    return { outcome: { outcome: 'selected', optionId: allow.optionId } }
  })
  const init = await rpc.request<{ authMethods?: { id: string }[] }>('initialize', {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false },
    clientInfo: { name: 'agentdeck', version: '0.1.0' }
  })
  const method = grok.authMethod((init.authMethods ?? []).map((auth) => auth.id), env)
  if (method) await rpc.request('authenticate', { methodId: method })
  const { sessionId } = await rpc.request<{ sessionId: string }>('session/new', { cwd, mcpServers: [] })
  const { stopReason } = await rpc.request<{ stopReason: string }>('session/prompt', {
    sessionId,
    prompt: [{ type: 'text', text: 'In notes.md, replace "hello world" with "goodbye world". Then reply with one short sentence.' }]
  })
  lines.push(JSON.stringify({ stopReason }))
  await stopGroup(child)
  mkdirSync('test/fixtures/grok', { recursive: true })
  writeFileSync(OUT, `${lines.join('\n')}\n`)
  console.log(`wrote ${lines.length} lines to ${OUT}`)
}

main().catch((error) => {
  console.error('RECORD FAILED:', error)
  process.exit(1)
})
