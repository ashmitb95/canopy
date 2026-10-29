import { describe, expect, it } from 'vitest'
import type { Question } from '../../src/core/types'
import { allAnswered, isAnswered, pick, setOther, toAnswers } from '../../webview/app/items/question-state'

const single: Question = {
  id: 'q1',
  question: 'Color?',
  multiSelect: false,
  allowOther: true,
  options: [
    { id: 'o1', label: 'Red' },
    { id: 'o2', label: 'Blue' }
  ]
}
const multi: Question = { ...single, id: 'q2', multiSelect: true }

describe('question state', () => {
  it('replaces the choice for single-select and clears typed text', () => {
    let draft = setOther({}, single, 'Green')
    draft = pick(draft, single, 'o1')
    draft = pick(draft, single, 'o2')
    expect(draft.q1).toEqual({ questionId: 'q1', optionIds: ['o2'] })
  })

  it('toggles choices for multi-select and keeps typed text', () => {
    let draft = pick({}, multi, 'o1')
    draft = pick(draft, multi, 'o2')
    draft = setOther(draft, multi, 'XL')
    draft = pick(draft, multi, 'o1')
    expect(draft.q2).toEqual({ questionId: 'q2', optionIds: ['o2'], other: 'XL' })
  })

  it('typing an answer to a single-select question clears its choice', () => {
    expect(setOther(pick({}, single, 'o1'), single, 'Green').q1).toEqual({ questionId: 'q1', optionIds: [], other: 'Green' })
  })

  it('knows when every question is answered', () => {
    const draft = pick({}, single, 'o1')
    expect(isAnswered(draft.q1)).toBe(true)
    expect(allAnswered([single, multi], draft)).toBe(false)
    expect(allAnswered([single, multi], setOther(draft, multi, ' x '))).toBe(true)
    expect(toAnswers([single], draft)).toEqual([{ questionId: 'q1', optionIds: ['o1'] }])
  })
})
