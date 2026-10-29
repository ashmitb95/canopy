import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { PermissionMode } from '../core/types'
import { parseToml } from './toml'

export type TaskType = { id: string; label: string; provider: string; mode: PermissionMode }

export const DEFAULT_TASKS: TaskType[] = [
  { id: 'research', label: 'Research', provider: 'grok', mode: 'ask' },
  { id: 'plan', label: 'Plan', provider: 'claude', mode: 'plan' },
  { id: 'build', label: 'Build', provider: 'codex', mode: 'accept-edits' },
  { id: 'review', label: 'Review', provider: 'claude', mode: 'ask' }
]

const MODES = new Set<string>(['ask', 'accept-edits', 'auto', 'plan', 'full-access'])

/** Task types from `[task.<id>]` tables in `.agentdeck/config.toml`, or the defaults when none are complete. */
export function readTasks(root: string): TaskType[] {
  const path = join(root, '.agentdeck', 'config.toml')
  const data = existsSync(path) ? parseToml(readFileSync(path, 'utf8')) : {}
  const tasks = Object.entries(data).flatMap(([key, value]) => {
    if (!key.startsWith('task.') || typeof value !== 'object' || value === null) return []
    const { label, provider, mode } = value as Record<string, unknown>
    if (typeof label !== 'string' || typeof provider !== 'string' || typeof mode !== 'string' || !MODES.has(mode)) return []
    return [{ id: key.slice('task.'.length), label, provider, mode: mode as PermissionMode }]
  })
  return tasks.length > 0 ? tasks : DEFAULT_TASKS
}

export type HandoffInput = { task: string; from: string; lane?: string; summaryPath?: string; reply?: string }

/** The first prompt of the next chat; the user edits it before it is sent. */
export function handoffPrompt(input: HandoffInput): string {
  if (input.lane && input.summaryPath) {
    return `You are taking over lane ${input.lane} for the ${input.task} step. Start from the previous chat “${input.from}” (summary: ${input.summaryPath}) and the lane plan, then continue.`
  }
  const quoted = (input.reply ?? '')
    .trim()
    .split('\n')
    .map((line) => `> ${line}`)
    .join('\n')
  return `You are taking over from the chat “${input.from}” for the ${input.task} step. Its last reply was:\n\n${quoted}\n\nContinue from there.`
}
