import type { SessionSummary } from '../../src/ui/protocol'

export type RecentGroup = { heading: string; sessions: SessionSummary[] }

/** The switcher's recent chats: one list, or grouped by lane (in order of each lane's most recent chat) with chats on no lane last. */
export function groupRecent(sessions: SessionSummary[]): RecentGroup[] {
  if (!sessions.some((session) => session.laneId)) return [{ heading: 'Recent', sessions }]
  const groups = new Map<string, SessionSummary[]>()
  for (const session of sessions) {
    if (!session.laneId) continue
    groups.set(session.laneId, [...(groups.get(session.laneId) ?? []), session])
  }
  const loose = sessions.filter((session) => !session.laneId)
  return [
    ...[...groups].map(([heading, grouped]) => ({ heading, sessions: grouped })),
    ...(loose.length > 0 ? [{ heading: 'No lane', sessions: loose }] : [])
  ]
}
