import type { Question, QuestionAnswer } from '../../../src/core/types'

export type Draft = Record<string, QuestionAnswer>

function current(draft: Draft, question: Question): QuestionAnswer {
  return draft[question.id] ?? { questionId: question.id, optionIds: [] }
}

/** Single-select replaces the choice and clears typed text; multi-select toggles. */
export function pick(draft: Draft, question: Question, optionId: string): Draft {
  const answer = current(draft, question)
  if (!question.multiSelect) return { ...draft, [question.id]: { questionId: question.id, optionIds: [optionId] } }
  const optionIds = answer.optionIds.includes(optionId)
    ? answer.optionIds.filter((id) => id !== optionId)
    : [...answer.optionIds, optionId]
  return { ...draft, [question.id]: { ...answer, optionIds } }
}

/** Typed text; for single-select it replaces any chosen option. */
export function setOther(draft: Draft, question: Question, text: string): Draft {
  const answer = current(draft, question)
  return {
    ...draft,
    [question.id]: { questionId: question.id, optionIds: question.multiSelect ? answer.optionIds : [], other: text }
  }
}

export function isAnswered(answer: QuestionAnswer | undefined): boolean {
  return Boolean(answer && (answer.optionIds.length > 0 || answer.other?.trim()))
}

export function allAnswered(questions: Question[], draft: Draft): boolean {
  return questions.every((question) => isAnswered(draft[question.id]))
}

export function toAnswers(questions: Question[], draft: Draft): QuestionAnswer[] {
  return questions.map((question) => current(draft, question))
}
