const DAYS = 30
const MAX = 100

/** The switcher's list: the last 30 days of chats (already newest first), capped. */
export function recentSessions<T extends { updatedAt: string }>(records: T[], now = Date.now()): T[] {
  return records.filter((record) => now - Date.parse(record.updatedAt) <= DAYS * 86_400_000).slice(0, MAX)
}
