import { PassThrough } from 'node:stream'
import { describe, expect, it } from 'vitest'
import { RpcPeer } from '../../src/providers/codex/rpc'

function connect() {
  const fromServer = new PassThrough()
  const toServer = new PassThrough()
  const peer = new RpcPeer(fromServer, toServer)
  const sent: Record<string, unknown>[] = []
  toServer.setEncoding('utf8')
  toServer.on('data', (chunk: string) => {
    for (const line of chunk.split('\n').filter(Boolean)) sent.push(JSON.parse(line))
  })
  const reply = (message: object) => fromServer.write(`${JSON.stringify(message)}\n`)
  const flush = () => new Promise((resolve) => setImmediate(resolve))
  return { peer, sent, reply, fromServer, flush }
}

describe('RpcPeer', () => {
  it('matches responses to requests', async () => {
    const { peer, sent, reply, flush } = connect()
    const result = peer.request('thread/start', { cwd: '/w' })
    await flush()
    expect(sent).toEqual([{ id: 1, method: 'thread/start', params: { cwd: '/w' } }])
    reply({ id: 1, result: { thread: { id: 't1' } } })
    await expect(result).resolves.toEqual({ thread: { id: 't1' } })
  })

  it('rejects on an error response', async () => {
    const { peer, reply } = connect()
    const result = peer.request('thread/resume', { threadId: 'x' })
    reply({ id: 1, error: { code: -32000, message: 'no rollout found' } })
    await expect(result).rejects.toThrow('thread/resume: no rollout found')
  })

  it('sends notifications without an id', async () => {
    const { peer, sent, flush } = connect()
    peer.notify('initialized')
    await flush()
    expect(sent).toEqual([{ method: 'initialized' }])
  })

  it('delivers notifications, including lines split across chunks', async () => {
    const { peer, fromServer, flush } = connect()
    const seen: unknown[] = []
    peer.onNotification((notification) => seen.push(notification))
    const line = JSON.stringify({ method: 'turn/started', params: { turn: { id: 'u1' } } })
    fromServer.write(line.slice(0, 10))
    fromServer.write(`${line.slice(10)}\n`)
    await flush()
    expect(seen).toEqual([{ method: 'turn/started', params: { turn: { id: 'u1' } } }])
  })

  it('answers server requests through the handler', async () => {
    const { peer, sent, reply, flush } = connect()
    peer.onRequest(async (request) => ({ decision: request.method === 'item/fileChange/requestApproval' ? 'accept' : 'decline' }))
    reply({ id: 7, method: 'item/fileChange/requestApproval', params: { itemId: 'f1' } })
    await flush()
    expect(sent).toEqual([{ id: 7, result: { decision: 'accept' } }])
  })

  it('returns an error for server requests the handler rejects', async () => {
    const { peer, sent, reply, flush } = connect()
    peer.onRequest(async () => {
      throw new Error('unsupported')
    })
    reply({ id: 8, method: 'item/tool/requestUserInput', params: {} })
    await flush()
    expect(sent).toEqual([{ id: 8, error: { code: -32601, message: 'unsupported' } }])
  })

  it('rejects pending requests when closed', async () => {
    const { peer } = connect()
    const result = peer.request('model/list', {})
    peer.close(new Error('codex exited'))
    await expect(result).rejects.toThrow('codex exited')
  })
})
