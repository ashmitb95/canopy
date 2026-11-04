import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { encodePrompt, imageParts } from '../../src/providers/encode'

function workspace(): string {
  const cwd = mkdtempSync(join(tmpdir(), 'canopy-encode-'))
  mkdirSync(join(cwd, 'src'))
  const lines = Array.from({ length: 300 }, (_, i) => `line ${i + 1}`)
  writeFileSync(join(cwd, 'src', 'a.ts'), lines.join('\n'))
  return cwd
}

describe('encodePrompt', () => {
  it('joins text parts with a blank line', () => {
    expect(encodePrompt([{ type: 'text', text: 'one' }, { type: 'text', text: 'two' }], '/w')).toBe('one\n\ntwo')
  })

  it('references a file relative to the workspace', () => {
    const cwd = workspace()
    expect(encodePrompt([{ type: 'file', path: join(cwd, 'src', 'a.ts') }], cwd)).toBe(
      '<editor-context file="src/a.ts" />'
    )
  })

  it('includes the selected lines', () => {
    const cwd = workspace()
    expect(encodePrompt([{ type: 'file', path: join(cwd, 'src', 'a.ts'), range: [2, 3] }], cwd)).toBe(
      '<editor-context file="src/a.ts" selection="2-3">\nline 2\nline 3\n</editor-context>'
    )
  })

  it('caps the selection at 200 lines', () => {
    const cwd = workspace()
    const encoded = encodePrompt([{ type: 'file', path: join(cwd, 'src', 'a.ts'), range: [1, 300] }], cwd)
    expect(encoded).toContain('line 200\n</editor-context>')
    expect(encoded).not.toContain('line 201')
  })

  it('puts slash commands first', () => {
    expect(encodePrompt([{ type: 'command', name: 'review' }, { type: 'text', text: 'focus on the API' }], '/w')).toBe('/review focus on the API')
  })

  it('includes pasted text and leaves images out of the text', () => {
    const parts = [
      { type: 'text' as const, text: 'Why does this fail?' },
      { type: 'pasted' as const, text: 'Error: boom\n  at x' },
      { type: 'image' as const, path: '/s/a.png', mimeType: 'image/png', name: 'a.png' }
    ]
    expect(encodePrompt(parts, '/w')).toBe('Why does this fail?\n\nError: boom\n  at x')
    expect(imageParts(parts)).toEqual([{ type: 'image', path: '/s/a.png', mimeType: 'image/png', name: 'a.png' }])
  })
})
