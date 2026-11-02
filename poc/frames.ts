// Replays recorded streams through the rolling view, as frames for the mockup.
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type { SessionItem } from '../src/core/types'
import { frameAt, type RollingLine } from './rolling'

const STEP_MS = 200
const [, , dir, ...names] = process.argv
const out: Record<string, { seconds: number; frames: { t: number; lines: RollingLine[] }[] }> = {}
for (const name of names) {
  const events = JSON.parse(readFileSync(join(dir, `${name}.json`), 'utf8')) as { t: number; item: SessionItem }[]
  const end = events.at(-1)?.t ?? 0
  const frames: { t: number; lines: RollingLine[] }[] = []
  let last = ''
  for (let t = 0; t <= end + STEP_MS; t += STEP_MS) {
    const lines = frameAt(events, t).map(({ id: _id, ...line }) => ({ id: '', ...line }))
    const key = JSON.stringify(lines)
    if (key !== last) frames.push({ t, lines })
    last = key
  }
  out[name] = { seconds: Math.ceil(end / 1000), frames }
  console.log(`${name}: ${frames.length} frames, ${out[name].seconds}s, ${frames.at(-1)?.lines.length} lines`)
}
writeFileSync(join(dir, 'frames.json'), JSON.stringify(out))
