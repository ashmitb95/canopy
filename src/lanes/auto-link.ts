import { resolve } from 'node:path'
import type { Disposable } from '../core/emitter'
import type { SessionManager } from '../sessions/manager'
import { laneFromPaths } from './lanes'
import type { LaneTracker } from './tracker'

/** After a turn, a chat on no lane joins the one lane its edits landed in. Agents may branch on their own; this keeps up. */
export function autoLink(manager: SessionManager, tracker: LaneTracker): Disposable {
  return manager.onAttention(({ sessionId, reason }) => {
    if (reason !== 'turn-ended') return
    void tracker.refresh().then(async () => {
      const record = manager.list().find((entry) => entry.record.id === sessionId)?.record
      if (!record || record.laneId) return
      const files = manager.diffPaths(sessionId).map((path) => resolve(tracker.root, path))
      const lane = laneFromPaths(tracker.repos, files)
      if (lane) await manager.setLane(sessionId, lane)
    })
  })
}
