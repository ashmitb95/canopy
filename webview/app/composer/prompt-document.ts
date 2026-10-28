import type { JSONContent } from '@tiptap/core'
import type { PromptPart } from '../../../src/core/types'

/** The composer's document as prompt parts: mentions and pills become their own parts, text between them merges. */
export function toParts(doc: JSONContent): PromptPart[] {
  const parts: PromptPart[] = []
  let text = ''
  const flush = () => {
    if (text.trim()) parts.push({ type: 'text', text: text.trim() })
    text = ''
  }
  ;(doc.content ?? []).forEach((block, index) => {
    if (index > 0) text += '\n'
    for (const node of block.content ?? []) {
      const attrs = node.attrs ?? {}
      if (node.type === 'text') text += node.text ?? ''
      else if (node.type === 'hardBreak') text += '\n'
      else {
        flush()
        if (node.type === 'mention' && attrs.mentionSuggestionChar === '/') parts.push({ type: 'command', name: String(attrs.id) })
        else if (node.type === 'mention') parts.push({ type: 'file', path: String(attrs.id) })
        else if (node.type === 'imageAttachment') {
          parts.push({ type: 'image', path: String(attrs.path), mimeType: String(attrs.mimeType), name: String(attrs.name) })
        } else if (node.type === 'pastedText') parts.push({ type: 'pasted', text: String(attrs.text) })
      }
    }
  })
  flush()
  return parts
}
