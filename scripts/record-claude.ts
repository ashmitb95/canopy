// Records a real Claude edit turn's SDK messages as a translator fixture.
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv } from '../src/env'
import { findClaude } from '../src/providers/claude/locate'

const OUT = 'test/fixtures/claude/edit-turn.jsonl'

async function main(): Promise<void> {
  const env = await captureEnv()
  const cli = await findClaude(env)
  if (!cli) throw new Error('claude CLI not found on the login-shell PATH')
  const { query } = await import('@anthropic-ai/claude-agent-sdk')
  const cwd = mkdtempSync(join(tmpdir(), 'canopy-record-'))
  writeFileSync(join(cwd, 'notes.md'), '# Notes\n\nhello world\n')

  const lines: string[] = []
  const messages = query({
    prompt: 'In notes.md, replace "hello world" with "goodbye world" using the Edit tool. Then reply with one short sentence.',
    options: {
      pathToClaudeCodeExecutable: cli,
      cwd,
      env,
      includePartialMessages: true,
      systemPrompt: { type: 'preset', preset: 'claude_code' },
      settingSources: [],
      permissionMode: 'acceptEdits'
    }
  })
  for await (const message of messages) {
    if (message.type === 'system' || message.type === 'rate_limit_event') continue
    lines.push(JSON.stringify(message))
  }
  mkdirSync('test/fixtures/claude', { recursive: true })
  writeFileSync(OUT, `${lines.join('\n')}\n`)
  console.log(`wrote ${lines.length} messages to ${OUT}`)
}

main().catch((error) => {
  console.error('RECORD FAILED:', error)
  process.exit(1)
})
