import { relative, resolve } from 'node:path'
import type { Disposable } from '../core/emitter'
import type { SessionManager } from '../sessions/manager'
import { linkChat } from './auto-link'
import { deriveLanes, type Lane, laneMoves } from './lanes'
import { type LaneMemory, stamp } from './memory'
import { chatSummary } from './summary'
import type { LaneTracker } from './tracker'

/** After each turn: refresh, link the chat to a lane if it has none, then write its summary into the lane. */
export function watchTurns(manager: SessionManager, tracker: LaneTracker, memory: LaneMemory): Disposable {
  return manager.onAttention(({ sessionId, reason }) => {
    if (reason !== 'turn-ended') return
    void (async () => {
      await tracker.refresh()
      await linkChat(manager, tracker, sessionId)
      const record = manager.list().find((entry) => entry.record.id === sessionId)?.record
      const laneId = record?.laneId
      if (!record || !laneId) return
      const lane = deriveLanes(tracker.repos, [laneId]).find((candidate) => candidate.name === laneId)
      memory.writeSummary(
        laneId,
        sessionId,
        chatSummary({
          stamp: stamp(`${record.providerId}:${sessionId.slice(0, 8)}`, lane?.repos ?? []),
          title: record.title,
          provider: record.providerId,
          root: tracker.root,
          files: manager.diffPaths(sessionId).map((path) => resolve(tracker.root, path)),
          reply: manager.lastReply(sessionId)
        })
      )
    })().catch(() => {})
  })
}

/** Appends observed lane moves to each lane's history. The first reading is a baseline, not a move. */
export function watchHistory(tracker: LaneTracker, memory: LaneMemory): Disposable {
  let before: Lane[] | undefined = tracker.repos.length > 0 ? deriveLanes(tracker.repos) : undefined
  return tracker.onDidChange(() => {
    const after = deriveLanes(tracker.repos)
    const rel = (path: string) => relative(tracker.root, path) || '.'
    for (const move of before ? laneMoves(before, after) : []) {
      memory.appendHistory(move.lane, {
        event: 'moved',
        repo: move.repo,
        ...(move.from ? { from: rel(move.from) } : {}),
        ...(move.to ? { to: rel(move.to) } : {})
      })
    }
    before = after
  })
}
