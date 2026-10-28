import { describe, expect, it } from 'vitest'
import { splitDiff, unwrapShell } from '../../src/providers/codex/text'

describe('unwrapShell', () => {
  it('removes the login-shell wrapper Codex adds', () => {
    expect(unwrapShell(`/bin/zsh -lc "grep -n -F 'hello world' notes.md"`)).toBe(`grep -n -F 'hello world' notes.md`)
    expect(unwrapShell(`bash -lc 'ls -la'`)).toBe('ls -la')
  })

  it('leaves other commands alone', () => {
    expect(unwrapShell('pnpm test')).toBe('pnpm test')
  })
})

describe('splitDiff', () => {
  it('keeps only changed lines from a unified diff', () => {
    const diff = ['--- a/notes.md', '+++ b/notes.md', '@@ -1,3 +1,3 @@', ' # Notes', '-hello world', '+goodbye world', ' end'].join('\n')
    expect(splitDiff(diff)).toEqual({ oldText: 'hello world', newText: 'goodbye world' })
  })

  it('treats a diff without hunks as new content', () => {
    expect(splitDiff('line one\nline two')).toEqual({ oldText: '', newText: 'line one\nline two' })
  })
})
