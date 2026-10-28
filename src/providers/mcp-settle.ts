import type { McpServer } from '../core/types'

type Options = { intervalMs: number; attempts: number; minAttempts?: number; closed?: () => boolean }

/**
 * Servers report `pending` while they connect, and some (claude.ai connectors) join the list late.
 * Re-read for at least `minAttempts`, then until none is pending, so the UI settles on real states.
 */
export async function refreshUntilSettled(
  read: () => Promise<McpServer[]>,
  emit: (servers: McpServer[]) => void,
  { intervalMs, attempts, minAttempts = 1, closed = () => false }: Options
): Promise<void> {
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const servers = await read()
    emit(servers)
    const settled = attempt >= minAttempts && !servers.some((server) => server.status === 'pending')
    if (settled || attempt === attempts) return
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
    if (closed()) return
  }
}
