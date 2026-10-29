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

/** Prompt parts as composer content: the inverse of `toParts`, for history, drafts, and editing queued messages. */
export function toDocument(parts: PromptPart[]): JSONContent {
  const paragraphs: JSONContent[][] = [[]]
  const current = () => paragraphs[paragraphs.length - 1]
  // Pills get a space on each side for reading; toParts trims text around them, so the parts come back unchanged.
  const pill = (node: JSONContent) => current().push(...(current().length > 0 ? [{ type: 'text', text: ' ' }] : []), node, { type: 'text', text: ' ' })
  for (const part of parts) {
    if (part.type === 'text') {
      part.text.split('\n').forEach((line, index) => {
        if (index > 0) paragraphs.push([])
        if (line) current().push({ type: 'text', text: line })
      })
    } else if (part.type === 'file') {
      pill({ type: 'mention', attrs: { id: part.path, label: part.path.split('/').pop() ?? part.path, mentionSuggestionChar: '@' } })
    } else if (part.type === 'command') {
      pill({ type: 'mention', attrs: { id: part.name, label: part.name, mentionSuggestionChar: '/' } })
    } else if (part.type === 'pasted') {
      pill({ type: 'pastedText', attrs: { text: part.text } })
    } else {
      pill({ type: 'imageAttachment', attrs: { path: part.path, mimeType: part.mimeType, name: part.name } })
    }
  }
  return { type: 'doc', content: paragraphs.map((content) => ({ type: 'paragraph', ...(content.length > 0 ? { content } : {}) })) }
}
