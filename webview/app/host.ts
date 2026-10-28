import type { HostMessage, WebviewMessage } from '../../src/ui/protocol'

type VsCodeApi = { postMessage(message: unknown): void; getState(): unknown; setState(state: unknown): void }

declare function acquireVsCodeApi(): VsCodeApi

const api = acquireVsCodeApi()

export function send(message: WebviewMessage): void {
  api.postMessage(message)
}

/** Lets VS Code restore an editor tab's session after a reload. */
export function saveState(state: { sessionId: string }): void {
  api.setState(state)
}

export function onHostMessage(listener: (message: HostMessage) => void): () => void {
  const handler = (event: MessageEvent<HostMessage>) => listener(event.data)
  window.addEventListener('message', handler)
  return () => window.removeEventListener('message', handler)
}

type Request = Extract<WebviewMessage, { requestId: number }>
type WithoutRequestId<T> = T extends unknown ? Omit<T, 'requestId'> : never

let nextRequest = 0
const replies = new Map<number, (value: unknown) => void>()

window.addEventListener('message', (event: MessageEvent<HostMessage>) => {
  if (event.data?.type !== 'reply') return
  replies.get(event.data.requestId)?.(event.data.value)
  replies.delete(event.data.requestId)
})

/** Sends a request to the extension host and resolves with its reply. */
export function ask<T>(message: WithoutRequestId<Request>): Promise<T> {
  const requestId = ++nextRequest
  return new Promise<T>((resolve) => {
    replies.set(requestId, resolve as (value: unknown) => void)
    send({ ...message, requestId } as Request)
  })
}
