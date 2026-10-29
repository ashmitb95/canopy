import type { Lane } from './lanes'

export type Grouped<T> = { lanes: { lane: Lane; sessions: T[] }[]; loose: T[] }

/** Sessions under their lane, in the given order; sessions on no known lane are loose. */
export function groupSessions<T extends { laneId?: string }>(lanes: Lane[], sessions: T[]): Grouped<T> {
  const names = new Set(lanes.map((lane) => lane.name))
  return {
    lanes: lanes.map((lane) => ({ lane, sessions: sessions.filter((session) => session.laneId === lane.name) })),
    loose: sessions.filter((session) => session.laneId === undefined || !names.has(session.laneId))
  }
}

export type ProviderGroup<T> = { provider: string } & Grouped<T>

/**
 * Sessions by provider, in the given provider order (unknown providers last); within each,
 * by lane as in groupSessions, leaving out lanes that provider has no chats on.
 */
export function groupByProvider<T extends { laneId?: string; provider: string }>(lanes: Lane[], sessions: T[], order: string[]): ProviderGroup<T>[] {
  const providers = [...new Set(sessions.map((session) => session.provider))]
  const rank = (provider: string) => (order.includes(provider) ? order.indexOf(provider) : order.length)
  return providers
    .sort((a, b) => rank(a) - rank(b))
    .map((provider) => {
      const grouped = groupSessions(lanes, sessions.filter((session) => session.provider === provider))
      return { provider, lanes: grouped.lanes.filter((group) => group.sessions.length > 0), loose: grouped.loose }
    })
}
