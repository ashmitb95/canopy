import { readFileSync } from 'node:fs'
import { relative, resolve } from 'node:path'
import type { PromptPart } from '../core/types'

const MAX_SELECTION_LINES = 200

/** Claude takes one text prompt; files become editor-context blocks after the user's text. */
export function encodePrompt(parts: PromptPart[], cwd: string): string {
  return parts.map((part) => (part.type === 'text' ? part.text : editorContext(part.path, part.range, cwd))).join('\n\n')
}

function editorContext(path: string, range: [number, number] | undefined, cwd: string): string {
  const absolute = resolve(cwd, path)
  const file = relative(cwd, absolute)
  if (!range) return `<editor-context file="${file}" />`
  const [start, end] = range
  let text = ''
  try {
    const lines = readFileSync(absolute, 'utf8').split('\n')
    text = lines.slice(start - 1, Math.min(end, start - 1 + MAX_SELECTION_LINES)).join('\n')
  } catch {
    // The file may have been deleted since it was selected; the reference alone still helps.
  }
  return `<editor-context file="${file}" selection="${start}-${end}">\n${text}\n</editor-context>`
}
