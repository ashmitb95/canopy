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
