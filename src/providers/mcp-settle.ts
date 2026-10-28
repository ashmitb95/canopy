import type { McpServer } from '../core/types'

type Options = { intervalMs: number; attempts: number; closed?: () => boolean }

/** Servers report `pending` while they connect; re-read until none is, so the UI settles on real states. */
export async function refreshUntilSettled(
  read: () => Promise<McpServer[]>,
  emit: (servers: McpServer[]) => void,
  { intervalMs, attempts, closed = () => false }: Options
): Promise<void> {
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const servers = await read()
    emit(servers)
    if (!servers.some((server) => server.status === 'pending') || attempt === attempts) return
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
    if (closed()) return
  }
}
