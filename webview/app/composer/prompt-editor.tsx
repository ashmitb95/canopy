import { mergeAttributes } from '@tiptap/core'
import Mention from '@tiptap/extension-mention'
import Placeholder from '@tiptap/extension-placeholder'
import { EditorContent, type JSONContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { forwardRef, useImperativeHandle, useRef } from 'react'
import type { CommandOption, PromptPart } from '../../../src/core/types'
import type { Attachment, FileMatch } from '../../../src/ui/protocol'
import { ask } from '../host'
import { commandMenu, fileMenu, ImageAttachment, PASTE_LINES, PastedText, SubmitOnEnter } from './nodes'
import { toParts } from './prompt-document'
import { renderMenu } from './suggestion-menu'

export type PromptEditorHandle = {
  submit: () => void
  insert: (attachments: Attachment[]) => void
  /** Types @ so the file menu opens. */
  mention: () => void
}

type Props = {
  placeholder: string
  commands: CommandOption[]
  onSubmit: (parts: PromptPart[]) => void
  onEmptyChange: (empty: boolean) => void
}

function attachmentNode(attachment: Attachment): JSONContent {
  return attachment.kind === 'image'
    ? { type: 'imageAttachment', attrs: { path: attachment.path, mimeType: attachment.mimeType, name: attachment.name } }
    : { type: 'mention', attrs: { id: attachment.path, label: attachment.label, mentionSuggestionChar: '@' } }
}

function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000))
  }
  return btoa(binary)
}

export const PromptEditor = forwardRef<PromptEditorHandle, Props>(function PromptEditor(
  { placeholder, commands, onSubmit, onEmptyChange },
  ref
) {
  const placeholderRef = useRef(placeholder)
  placeholderRef.current = placeholder
  const commandsRef = useRef(commands)
  commandsRef.current = commands
  const submitRef = useRef(() => {})

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        blockquote: false,
        bold: false,
        bulletList: false,
        code: false,
        codeBlock: false,
        dropcursor: false,
        gapcursor: false,
        heading: false,
        horizontalRule: false,
        italic: false,
        link: false,
        listItem: false,
        orderedList: false,
        strike: false,
        trailingNode: false,
        underline: false
      }),
      Placeholder.configure({ placeholder: () => placeholderRef.current }),
      Mention.configure({
        HTMLAttributes: { 'data-pill': 'mention' },
        deleteTriggerWithBackspace: true,
        renderText: ({ node }) => `${node.attrs.mentionSuggestionChar ?? '@'}${node.attrs.label ?? node.attrs.id}`,
        renderHTML: ({ options, node }) => [
          'span',
          mergeAttributes({ 'data-type': 'mention' }, options.HTMLAttributes),
          `${node.attrs.mentionSuggestionChar ?? '@'}${node.attrs.label ?? node.attrs.id}`
        ],
        suggestions: [
          {
            char: '@',
            pluginKey: fileMenu,
            items: async ({ query }) =>
              (await ask<FileMatch[]>({ type: 'searchFiles', query })).map((file) => ({ id: file.path, label: file.label })),
            render: renderMenu('Files')
          },
          {
            char: '/',
            pluginKey: commandMenu,
            items: ({ query }) =>
              commandsRef.current
                .filter((command) => command.name.toLowerCase().includes(query.toLowerCase()))
                .slice(0, 30)
                .map((command) => ({ id: command.name, label: command.name, description: command.description })),
            render: renderMenu('Commands and skills')
          }
        ]
      }),
      ImageAttachment,
      PastedText,
      SubmitOnEnter.configure({ onSubmit: () => submitRef.current() })
    ],
    editorProps: {
      attributes: { class: 'prompt-editor', role: 'textbox', 'aria-multiline': 'true', 'aria-label': 'Message' },
      handlePaste: (_view, event) => {
        const images = [...(event.clipboardData?.files ?? [])].filter((file) => file.type.startsWith('image/'))
        if (images.length > 0) {
          void Promise.all(
            images.map(async (file) =>
              ask<Attachment>({ type: 'saveImage', name: file.name || 'pasted image', mimeType: file.type, data: toBase64(await file.arrayBuffer()) })
            )
          ).then(insert)
          return true
        }
        const text = event.clipboardData?.getData('text/plain') ?? ''
        if (text.split('\n').length <= PASTE_LINES) return false
        editor?.chain().focus().insertContent([{ type: 'pastedText', attrs: { text } }, { type: 'text', text: ' ' }]).run()
        return true
      }
    },
    onUpdate: ({ editor: current }) => onEmptyChange(current.isEmpty)
  })

  const insert = (attachments: Attachment[]) => {
    if (!editor || attachments.length === 0) return
    editor.chain().focus().insertContent([...attachments.map(attachmentNode), { type: 'text', text: ' ' }]).run()
  }

  submitRef.current = () => {
    if (!editor) return
    const parts = toParts(editor.getJSON())
    if (parts.length === 0) return
    onSubmit(parts)
    editor.commands.clearContent(true)
  }

  useImperativeHandle(ref, () => ({
    submit: () => submitRef.current(),
    insert,
    mention: () => editor?.chain().focus().insertContent('@').run()
  }))

  return <EditorContent editor={editor} />
})
