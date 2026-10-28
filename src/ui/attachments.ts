import { randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { basename, extname, join } from 'node:path'
import type { Attachment } from './protocol'

const IMAGE_TYPES: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp'
}

/** Images are copied into the extension's storage, so the transcript can show them after the original moves. */
export function saveImage(dir: string, name: string, mimeType: string, data: Buffer): Attachment {
  mkdirSync(dir, { recursive: true })
  const extension = Object.entries(IMAGE_TYPES).find(([, type]) => type === mimeType)?.[0] ?? '.png'
  const path = join(dir, `${randomUUID()}${extension}`)
  writeFileSync(path, data)
  return { kind: 'image', path, mimeType, name }
}

/** A picked image is stored like a pasted one; any other file is referenced where it is. */
export function attachFile(dir: string, source: string, label: string): Attachment {
  const type = IMAGE_TYPES[extname(source).toLowerCase()]
  return type ? saveImage(dir, basename(source), type, readFileSync(source)) : { kind: 'file', path: source, label }
}
