import { describe, expect, it } from 'vitest'
import { approvalDetail, toolKind, toolPaths, toolTitle } from '../../src/providers/claude/tools'

describe('Claude tool descriptions', () => {
  it('classifies tools', () => {
    expect(toolKind('Read')).toBe('read')
    expect(toolKind('Edit')).toBe('edit')
    expect(toolKind('Bash')).toBe('execute')
    expect(toolKind('Grep')).toBe('search')
    expect(toolKind('WebFetch')).toBe('fetch')
    expect(toolKind('mcp__notion__search')).toBe('mcp')
    expect(toolKind('Task')).toBe('other')
  })

  it('titles a tool with its target', () => {
    expect(toolTitle('Bash', { command: 'pnpm test' })).toBe('Bash pnpm test')
    expect(toolTitle('Read', { file_path: '/w/a.ts' })).toBe('Read /w/a.ts')
    expect(toolTitle('Task', { prompt: 'x' })).toBe('Task')
  })

  it('titles an MCP tool as server and tool', () => {
    expect(toolTitle('mcp__notion__search_pages', {})).toBe('notion · search_pages')
  })

  it('shortens long targets', () => {
    expect(toolTitle('Bash', { command: 'x'.repeat(200) })).toHaveLength('Bash '.length + 120)
  })

  it('lists file paths a tool touches', () => {
    expect(toolPaths({ file_path: '/w/a.ts' })).toEqual(['/w/a.ts'])
    expect(toolPaths({ notebook_path: '/w/n.ipynb' })).toEqual(['/w/n.ipynb'])
    expect(toolPaths({ command: 'ls' })).toBeUndefined()
  })

  it('describes what an approval would allow', () => {
    expect(approvalDetail({ command: 'rm -rf build' })).toBe('rm -rf build')
    expect(approvalDetail({ file_path: '/w/a.ts', content: 'x' })).toBe('/w/a.ts')
    expect(approvalDetail({ query: 'q' })).toBe('{\n  "query": "q"\n}')
  })
})
