import { readFileSync } from 'node:fs'
import { relative, resolve } from 'node:path'
import type { PromptPart } from '../core/types'

const MAX_SELECTION_LINES = 200

/** The prompt as text: slash commands lead, files become editor-context blocks, images travel separately. */
export function encodePrompt(parts: PromptPart[], cwd: string): string {
  const commands = parts.flatMap((part) => (part.type === 'command' ? [`/${part.name}`] : []))
  const body = parts
    .flatMap((part) => {
      switch (part.type) {
        case 'text':
        case 'pasted':
          return [part.text]
        case 'file':
          return [editorContext(part.path, part.range, cwd)]
        default:
          return []
      }
    })
    .join('\n\n')
  return commands.length > 0 ? [commands.join(' '), body].filter(Boolean).join(' ') : body
}

export function imageParts(parts: PromptPart[]): Extract<PromptPart, { type: 'image' }>[] {
  return parts.filter((part): part is Extract<PromptPart, { type: 'image' }> => part.type === 'image')
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
