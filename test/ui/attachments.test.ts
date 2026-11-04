import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { attachFile, saveImage } from '../../src/ui/attachments'

describe('attachments', () => {
  it('stores an image under a new name', () => {
    const dir = join(mkdtempSync(join(tmpdir(), 'canopy-att-')), 'attachments')
    const image = saveImage(dir, 'shot.png', 'image/png', Buffer.from('png-bytes'))
    expect(image).toMatchObject({ kind: 'image', mimeType: 'image/png', name: 'shot.png' })
    expect(image.kind === 'image' && image.path.startsWith(dir) && image.path.endsWith('.png')).toBe(true)
    expect(readFileSync(image.path, 'utf8')).toBe('png-bytes')
  })

  it('copies picked images and references other files in place', () => {
    const root = mkdtempSync(join(tmpdir(), 'canopy-att-'))
    const dir = join(root, 'attachments')
    writeFileSync(join(root, 'diagram.jpg'), 'jpg-bytes')
    writeFileSync(join(root, 'notes.ts'), 'code')
    const image = attachFile(dir, join(root, 'diagram.jpg'), 'diagram.jpg')
    expect(image).toMatchObject({ kind: 'image', mimeType: 'image/jpeg', name: 'diagram.jpg' })
    expect(image.kind === 'image' && existsSync(image.path)).toBe(true)
    expect(attachFile(dir, join(root, 'notes.ts'), 'notes.ts')).toEqual({ kind: 'file', path: join(root, 'notes.ts'), label: 'notes.ts' })
  })
})
