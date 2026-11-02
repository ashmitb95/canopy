import { relative } from 'node:path'
import type { LaneSeen } from '../sessions/store'
import type { Lane, LaneRepo } from './lanes'

const MAX_EARLIER = 5

const RULES =
  'Rules: edit only inside the code paths above. Do not switch branches in primary checkouts. Keep plan.md current as steps finish; add decisions and findings to notes.md as "- " bullets.'

export type BriefInput = {
  root: string
  lane: Lane
  goal?: string
  plan: { path: string; updated?: string }
  notes: { path: string; entries: number }
  earlier: { title: string; path: string }[]
}

function where(root: string, repo: LaneRepo): string {
  const path = relative(root, repo.path) || '.'
  const state = repo.dirty > 0 ? `${repo.dirty} uncommitted` : 'clean'
  return repo.location === 'primary' ? `${path}/ (primary checkout, ${state})` : `${path} (worktree, ${state})`
}

/** The first-turn brief: pointers, not content; the agent reads what it needs. */
export function buildBrief(input: BriefInput): string {
  const rel = (path: string) => relative(input.root, path)
  const code =
    input.lane.repos.length > 0
      ? input.lane.repos.map((repo) => where(input.root, repo)).join(' · ')
      : `no checkout yet (branch ${input.lane.name})`
  const earlier = input.earlier.slice(0, MAX_EARLIER).map((chat) => `${chat.title} (${rel(chat.path)})`)
  return [
    `<lane name="${input.lane.name}">`,
    `Goal: ${input.goal ?? 'not set'}`,
    `Code: ${code}`,
    `Plan: ${rel(input.plan.path)} (${input.plan.updated ? `updated ${input.plan.updated}` : 'empty'})`,
    `Notes: ${rel(input.notes.path)} (${input.notes.entries} ${input.notes.entries === 1 ? 'entry' : 'entries'})`,
    ...(earlier.length > 0 ? [`Earlier chats: ${earlier.join('; ')}`] : []),
    RULES,
    '</lane>'
  ].join('\n')
}

export function seenOf(lane: Lane, at = new Date()): LaneSeen {
  return {
    lane: lane.name,
    at: at.toISOString(),
    repos: Object.fromEntries(lane.repos.map((repo) => [repo.repo, { path: repo.path, ...(repo.head ? { head: repo.head } : {}) }]))
  }
}

/** What changed for this lane since the chat last looked, or undefined when nothing did. */
export function buildDelta(root: string, lane: Lane, seen: LaneSeen, planUpdated?: string): string | undefined {
  const rel = (path: string) => relative(root, path) || '.'
  const now = new Map(lane.repos.map((repo) => [repo.repo, repo]))
  const lines: string[] = []
  for (const [repo, before] of Object.entries(seen.repos)) {
    const after = now.get(repo)
    if (!after) lines.push(`- ${repo}: left the lane (no checkout now).`)
    else if (after.path !== before.path) lines.push(`- ${repo}: moved from ${rel(before.path)} to ${rel(after.path)}; work there now.`)
    else if (before.head && after.head && before.head !== after.head) {
      lines.push(`- ${repo}: new commits (${before.head.slice(0, 7)} → ${after.head.slice(0, 7)}).`)
    }
  }
  for (const repo of lane.repos) if (!(repo.repo in seen.repos)) lines.push(`- ${repo.repo}: joined the lane at ${rel(repo.path)}.`)
  if (planUpdated && planUpdated > seen.at) lines.push('- plan.md changed.')
  if (lines.length === 0) return undefined
  return [`<lane-update name="${lane.name}">`, 'Since your last turn:', ...lines, '</lane-update>'].join('\n')
}
