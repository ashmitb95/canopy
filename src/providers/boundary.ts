import { resolve, sep } from 'node:path'
import type { WriteBoundary } from '../core/types'

export const BRANCH_SWITCH =
  "Branch switches are AgentDeck's job (Move into Main, Move to Worktrees in the Sessions list). Keep working in this lane's paths."

const within = (paths: string[], path: string) => paths.some((root) => path === root || path.startsWith(root + sep))

export function writable(boundary: Pick<WriteBoundary, 'roots' | 'except'>, path: string): boolean {
  return within(boundary.roots, path) && !within(boundary.except, path)
}

const PATH_KEYS: Record<string, string> = { Edit: 'file_path', Write: 'file_path', MultiEdit: 'file_path', NotebookEdit: 'notebook_path' }

/** The files a Claude tool call writes, absolute. */
export function claudeWritePaths(toolName: string, input: Record<string, unknown>, cwd: string): string[] {
  const key = PATH_KEYS[toolName]
  const value = key ? input[key] : undefined
  return typeof value === 'string' ? [resolve(cwd, value)] : []
}

/** A shell command that switches branches; `git checkout -- <file>` (restoring files) is not one. */
export function switchesBranch(command: string): boolean {
  return /\bgit\s+(?:-C\s+\S+\s+)?(?:checkout|switch)\b(?!.*\s--\s)/.test(command)
}
