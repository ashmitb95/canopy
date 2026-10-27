// Live check outside VS Code: sign-in state, a chat turn, and an approved file edit.
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { ClaudeChat, claudeAuthStatus, resolveClaudeCli } from '../src/claude-session'

async function main(): Promise<void> {
  const cli = await resolveClaudeCli()
  if (!cli) throw new Error('claude CLI not found on the login-shell PATH')
  const auth = await claudeAuthStatus(cli)
  console.log('cli:', cli.path)
  console.log('auth:', auth.loggedIn, auth.authMethod)

  const dir = mkdtempSync(join(tmpdir(), 'agentdeck-smoke-'))
  const file = join(dir, 'notes.md')
  writeFileSync(file, '# Notes\n\nhello world\n')

  let done = (): void => {}
  let reply = ''
  const chat = new ClaudeChat(cli, dir, (event) => {
    if (event.type === 'text') {
      reply += event.delta
      return process.stdout.write(event.delta)
    }
    console.log('\n[event]', JSON.stringify(event).slice(0, 1500))
    if (event.type === 'permission') chat.respondToPermission(event.id, true)
    if (event.type === 'turn_end' || event.type === 'error') done()
  })
  const turn = (text: string): Promise<void> => {
    reply = ''
    const ended = new Promise<void>((resolve) => (done = resolve))
    chat.send(text)
    return ended
  }
  await turn('In notes.md, replace "hello world" with "goodbye world". Use the Edit tool. Reply with one short sentence.')
  // A second turn on the same process must remember the first.
  await turn('What word did you just replace? Answer with that single word only.')
  chat.close()
  if (!/hello/i.test(reply)) throw new Error(`second turn lost context: ${JSON.stringify(reply)}`)

  const after = readFileSync(file, 'utf8')
  console.log('\nfile after:', JSON.stringify(after))
  if (!after.includes('goodbye world')) throw new Error('edit was not applied')
  console.log('SMOKE OK')
}

main().catch((error) => {
  console.error('SMOKE FAILED:', error)
  process.exit(1)
})
