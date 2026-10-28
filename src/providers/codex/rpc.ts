import type { Readable, Writable } from 'node:stream'
import { Emitter } from '../../core/emitter'

export type Notification = { method: string; params: unknown }
export type ServerRequest = { id: number | string; method: string; params: unknown }

type Pending = { method: string; resolve: (result: unknown) => void; reject: (error: Error) => void }
type Incoming = {
  id?: number | string
  method?: string
  params?: unknown
  result?: unknown
  error?: { message?: string }
}

/** JSON-RPC as `codex app-server` speaks it: one JSON object per line, no "jsonrpc" field. */
export class RpcPeer {
  private seq = 0
  private buffer = ''
  private readonly pending = new Map<number, Pending>()
  private readonly notifications = new Emitter<Notification>()
  readonly onNotification = this.notifications.event
  private handler: (request: ServerRequest) => Promise<unknown> = async (request) => {
    throw new Error(`Unsupported request: ${request.method}`)
  }

  constructor(
    input: Readable,
    private readonly output: Writable,
    private readonly log: (message: string) => void = () => {}
  ) {
    input.setEncoding('utf8')
    input.on('data', (chunk: string) => this.receive(chunk))
  }

  onRequest(handler: (request: ServerRequest) => Promise<unknown>): void {
    this.handler = handler
  }

  request<T>(method: string, params?: unknown): Promise<T> {
    const id = ++this.seq
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { method, resolve: resolve as (result: unknown) => void, reject })
      this.write(params === undefined ? { id, method } : { id, method, params })
    })
  }

  notify(method: string, params?: unknown): void {
    this.write(params === undefined ? { method } : { method, params })
  }

  /** Fails every outstanding request, e.g. when the process exits. */
  close(error: Error): void {
    for (const pending of this.pending.values()) pending.reject(error)
    this.pending.clear()
  }

  private write(message: object): void {
    this.output.write(`${JSON.stringify(message)}\n`)
  }

  private receive(chunk: string): void {
    this.buffer += chunk
    let newline = this.buffer.indexOf('\n')
    while (newline >= 0) {
      const line = this.buffer.slice(0, newline).trim()
      this.buffer = this.buffer.slice(newline + 1)
      if (line) this.dispatch(line)
      newline = this.buffer.indexOf('\n')
    }
  }

  private dispatch(line: string): void {
    let message: Incoming
    try {
      message = JSON.parse(line) as Incoming
    } catch {
      this.log(`Skipped an unparseable app-server line: ${line.slice(0, 200)}`)
      return
    }
    if (message.method !== undefined && message.id !== undefined) {
      void this.serve({ id: message.id, method: message.method, params: message.params })
    } else if (message.method !== undefined) {
      this.notifications.fire({ method: message.method, params: message.params })
    } else {
      this.settle(Number(message.id), message)
    }
  }

  private settle(id: number, message: Incoming): void {
    const pending = this.pending.get(id)
    if (!pending) return
    this.pending.delete(id)
    if (message.error) pending.reject(new Error(`${pending.method}: ${message.error.message ?? 'request failed'}`))
    else pending.resolve(message.result)
  }

  private async serve(request: ServerRequest): Promise<void> {
    try {
      this.write({ id: request.id, result: await this.handler(request) })
    } catch (error) {
      this.write({ id: request.id, error: { code: -32601, message: error instanceof Error ? error.message : String(error) } })
    }
  }
}
