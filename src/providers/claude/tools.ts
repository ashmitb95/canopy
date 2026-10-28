import type { ToolKind } from '../../core/types'

const KINDS: Record<string, ToolKind> = {
  Read: 'read',
  NotebookRead: 'read',
  Edit: 'edit',
  MultiEdit: 'edit',
  Write: 'edit',
  NotebookEdit: 'edit',
  Bash: 'execute',
  Grep: 'search',
  Glob: 'search',
  WebFetch: 'fetch',
  WebSearch: 'fetch'
}

const TARGET_KEYS = ['file_path', 'notebook_path', 'command', 'pattern', 'url', 'query']
const MAX_TARGET = 120

export function toolKind(name: string): ToolKind {
  if (name.startsWith('mcp__')) return 'mcp'
  return KINDS[name] ?? 'other'
}

export function toolTitle(name: string, input: Record<string, unknown>): string {
  if (name.startsWith('mcp__')) {
    const [, server, ...tool] = name.split('__')
    return `${server} · ${tool.join('__')}`
  }
  const target = firstString(input, TARGET_KEYS)
  return target ? `${name} ${target.slice(0, MAX_TARGET)}` : name
}

export function toolPaths(input: Record<string, unknown>): string[] | undefined {
  const path = firstString(input, ['file_path', 'notebook_path'])
  return path ? [path] : undefined
}

export function approvalDetail(input: Record<string, unknown>): string {
  return firstString(input, ['command', 'file_path', 'notebook_path', 'url']) ?? JSON.stringify(input, null, 2).slice(0, 2000)
}

function firstString(input: Record<string, unknown>, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = input[key]
    if (typeof value === 'string') return value
  }
  return undefined
}
