import { Extension, mergeAttributes, Node } from '@tiptap/core'
import { type EditorState, PluginKey } from '@tiptap/pm/state'

export const fileMenu = new PluginKey('fileMenu')
export const commandMenu = new PluginKey('commandMenu')

function menuOpen(state: EditorState): boolean {
  return [fileMenu, commandMenu].some((key) => key.getState(state)?.active)
}

/** Enter sends; while an @ or / menu is open it picks the highlighted entry instead. Shift+Enter adds a line. */
export const SubmitOnEnter = Extension.create<{ onSubmit: () => void }>({
  name: 'submitOnEnter',
  priority: 1000,
  addOptions: () => ({ onSubmit: () => {} }),
  addKeyboardShortcuts() {
    return {
      Enter: ({ editor }) => {
        if (menuOpen(editor.state)) return false
        this.options.onSubmit()
        return true
      }
    }
  }
})

/** An image in AgentDeck's attachment store. */
export const ImageAttachment = Node.create({
  name: 'imageAttachment',
  group: 'inline',
  inline: true,
  atom: true,
  addAttributes: () => ({ path: { default: '' }, mimeType: { default: 'image/png' }, name: { default: 'image' } }),
  parseHTML: () => [{ tag: 'span[data-pill="image"]' }],
  renderHTML: ({ node, HTMLAttributes }) => [
    'span',
    mergeAttributes(HTMLAttributes, { 'data-pill': 'image' }),
    ['i', { class: 'codicon codicon-file-media' }],
    ` ${node.attrs.name}`
  ],
  renderText: ({ node }) => `[image: ${node.attrs.name}]`
})

export const PASTE_LINES = 40

/** A long paste, kept whole but shown as one pill. */
export const PastedText = Node.create({
  name: 'pastedText',
  group: 'inline',
  inline: true,
  atom: true,
  addAttributes: () => ({ text: { default: '' } }),
  parseHTML: () => [{ tag: 'span[data-pill="pasted"]' }],
  renderHTML: ({ node, HTMLAttributes }) => [
    'span',
    mergeAttributes(HTMLAttributes, { 'data-pill': 'pasted', title: String(node.attrs.text).slice(0, 2000) }),
    `Pasted text · ${String(node.attrs.text).split('\n').length} lines`
  ],
  renderText: ({ node }) => String(node.attrs.text)
})
