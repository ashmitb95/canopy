import { describe, expect, it } from 'vitest'
import { toParts } from '../../webview/app/composer/prompt-document'

const doc = (...paragraphs: object[][]) => ({ type: 'doc', content: paragraphs.map((content) => ({ type: 'paragraph', content })) })
const text = (value: string) => ({ type: 'text', text: value })

describe('toParts', () => {
  it('turns mentions and pills into parts and merges text', () => {
    expect(
      toParts(
        doc(
          [{ type: 'mention', attrs: { id: 'review', label: 'review', mentionSuggestionChar: '/' } }, text(' the retry change in ')],
          [{ type: 'mention', attrs: { id: '/w/src/retry.ts', label: 'src/retry.ts', mentionSuggestionChar: '@' } }, text(' please')],
          [{ type: 'imageAttachment', attrs: { path: '/s/a.png', mimeType: 'image/png', name: 'a.png' } }],
          [{ type: 'pastedText', attrs: { text: 'line 1\nline 2' } }]
        )
      )
    ).toEqual([
      { type: 'command', name: 'review' },
      { type: 'text', text: 'the retry change in' },
      { type: 'file', path: '/w/src/retry.ts' },
      { type: 'text', text: 'please' },
      { type: 'image', path: '/s/a.png', mimeType: 'image/png', name: 'a.png' },
      { type: 'pasted', text: 'line 1\nline 2' }
    ])
  })

  it('keeps line breaks inside text and drops empty text', () => {
    expect(toParts(doc([text('one')], [text('two'), { type: 'hardBreak' }, text('three')], []))).toEqual([
      { type: 'text', text: 'one\ntwo\nthree' }
    ])
    expect(toParts(doc([]))).toEqual([])
  })
})
