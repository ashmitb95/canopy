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
