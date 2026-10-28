import { describe, expect, it } from 'vitest'
import type { McpServer } from '../../src/core/types'
import { refreshUntilSettled } from '../../src/providers/mcp-settle'

const server = (status: McpServer['status']): McpServer => ({ name: 'notion', status, tools: [] })

function reader(...results: McpServer[][]) {
  let calls = 0
  return {
    read: async () => results[Math.min(calls++, results.length - 1)],
    calls: () => calls
  }
}

describe('refreshUntilSettled', () => {
  it('re-reads while a server is pending and emits every reading', async () => {
    const { read, calls } = reader([server('pending')], [server('pending')], [server('connected')])
    const emitted: McpServer[][] = []
    await refreshUntilSettled(read, (servers) => emitted.push(servers), { intervalMs: 0, attempts: 10 })
    expect(calls()).toBe(3)
    expect(emitted.at(-1)).toEqual([server('connected')])
  })

  it('stops after the attempt limit', async () => {
    const { read, calls } = reader([server('pending')])
    await refreshUntilSettled(read, () => {}, { intervalMs: 0, attempts: 4 })
    expect(calls()).toBe(4)
  })

  it('stops when the session closes', async () => {
    const { read, calls } = reader([server('pending')])
    let closed = false
    await refreshUntilSettled(
      read,
      () => {
        closed = true
      },
      { intervalMs: 0, attempts: 10, closed: () => closed }
    )
    expect(calls()).toBe(1)
  })
})
