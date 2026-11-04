// Live check: each provider's CLI can call a tool on one local server and read its result.
import { mkdtempSync, realpathSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { SessionItem } from '../src/core/types'
import { captureEnv } from '../src/env'
import { providers } from '../src/providers/registry'
import { startToolServer } from '../src/group/tool-server'

const TIMEOUT_MS = 180_000

async function probe(providerId: string): Promise<string> {
  const provider = providers.get(providerId)
  if (!provider) return 'unknown provider'
  const calls: Record<string, unknown>[] = []
  const secret = `token-${Date.now().toString(36)}`
  const server = await startToolServer([
    {
      name: 'delegate',
      description: 'Hands a task to another agent and returns its report.',
      inputSchema: { type: 'object', properties: { provider: { type: 'string' }, task: { type: 'string' } }, required: ['provider', 'task'] },
      call: (args) => {
        calls.push(args)
        return `Report from ${String(args.provider)}: finished. Confirmation code ${secret}.`
      }
    }
  ])
  const cwd = realpathSync(mkdtempSync(join(tmpdir(), 'canopy-tools-')))
  const session = await provider.open({ env: await captureEnv(), cwd, mode: 'full-access', toolServer: { name: 'canopy', url: server.url } })
  const texts: string[] = []
  let done: () => void = () => {}
  const ended = new Promise<void>((resolve) => (done = resolve))
  session.onItem((item: SessionItem) => {
    if (item.kind === 'message' && item.role === 'assistant') texts.push(item.text)
    if (item.kind === 'turn' && item.state === 'ended') done()
    if (item.kind === 'approval') session.answer(item.id, { kind: 'option', optionId: 'allow' })
  })
  session.onExit(({ error }) => {
    if (error) console.log(`  ${providerId} exit: ${error.slice(0, 200)}`)
    done()
  })
  await session.prompt([{ type: 'text', text: 'Call the delegate tool from the canopy MCP server with provider "grok" and task "say hello". Then reply with the confirmation code it returned, and nothing else.' }])
  await Promise.race([ended, new Promise((resolve) => setTimeout(resolve, TIMEOUT_MS))])
  await session.dispose()
  server.close()
  const reply = texts.at(-1) ?? ''
  const methods = [...new Set(server.methods)].join(',')
  if (calls.length === 0) return `FAIL no tool call. server saw: ${methods || 'nothing'}. reply: ${reply.slice(0, 160)}`
  return reply.includes(secret) ? `OK called ${calls.length}x, result reached the agent. server saw: ${methods}` : `PARTIAL called, but the reply lacks the code. reply: ${reply.slice(0, 160)}`
}

async function main(): Promise<void> {
  for (const id of process.argv.slice(2)) console.log(`${id}: ${await probe(id).catch((error: Error) => `ERROR ${error.message.slice(0, 200)}`)}`)
  process.exit(0)
}

void main()
