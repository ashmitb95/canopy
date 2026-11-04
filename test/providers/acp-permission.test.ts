import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { acpProvider } from '../../src/providers/acp/provider'

const until = async (check: () => boolean) => {
  for (let i = 0; i < 200 && !check(); i++) await new Promise((done) => setTimeout(done, 10))
}

describe('ACP permission requests', () => {
  it("answers later requests of a kind itself once the user says not to ask again, even if the agent asks anyway", async () => {
    const provider = acpProvider({ id: 'fake', label: 'Fake', command: 'fake-agent', installUrl: '', args: [], loginArgs: [], installDirs: () => [resolve('test/fixtures/acp')], authMethod: () => undefined, signedIn: () => true })
    const session = await provider.open({ env: { PATH: process.env.PATH ?? '' }, cwd: join(process.cwd()), mode: 'ask' })
    const items = new Map<string, SessionItem>()
    session.onItem((item) => items.set(item.id, item))
    void session.prompt([{ type: 'text', text: 'go' }])
    await until(() => items.has('approval:c1'))
    session.answer('approval:c1', { kind: 'option', optionId: 'allowForSession' })
    await until(() => [...items.values()].some((item) => item.kind === 'message' && item.role === 'assistant' && item.text.includes(',')))
    expect(items.has('approval:c2')).toBe(false)
    const reply = [...items.values()].find((item) => item.kind === 'message' && item.role === 'assistant')
    expect(reply).toMatchObject({ text: 'always,always' })
    await session.dispose()
  })
})
