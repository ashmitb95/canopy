import type { Question, QuestionAnswer } from '../core/types'

function answerFor(question: Question, answers: QuestionAnswer[]): QuestionAnswer | undefined {
  return answers.find((answer) => answer.questionId === question.id)
}

function labels(question: Question, answer: QuestionAnswer | undefined): string[] {
  return (answer?.optionIds ?? []).flatMap((id) => question.options.find((option) => option.id === id)?.label ?? [])
}

/** The chosen labels for one question, with the user's own text last. */
function values(question: Question, answer: QuestionAnswer | undefined): string[] {
  const other = answer?.other?.trim()
  return other ? [...labels(question, answer), other] : labels(question, answer)
}

/** Claude's AskUserQuestion: answers keyed by question text; multi-select answers are comma-separated. */
export function claudeAnswers(questions: Question[], answers: QuestionAnswer[]): Record<string, string> {
  return Object.fromEntries(questions.map((question) => [question.question, values(question, answerFor(question, answers)).join(', ')]))
}

/** Codex's item/tool/requestUserInput: answers keyed by question id. */
export function codexAnswers(questions: Question[], answers: QuestionAnswer[]): { answers: Record<string, { answers: string[] }> } {
  return {
    answers: Object.fromEntries(questions.map((question) => [question.id, { answers: values(question, answerFor(question, answers)) }]))
  }
}

/** Grok's x.ai/ask_user_question: labels keyed by question text (an array for multi-select); typed text goes in annotations. */
export function grokAnswers(questions: Question[], answers: QuestionAnswer[]) {
  const result: {
    outcome: 'accepted'
    answers: Record<string, string | string[]>
    annotations?: Record<string, { notes: string }>
  } = { outcome: 'accepted', answers: {} }
  for (const question of questions) {
    const answer = answerFor(question, answers)
    const chosen = labels(question, answer)
    const other = answer?.other?.trim()
    if (other) {
      if (chosen.length === 0) chosen.push('Other')
      result.annotations = { ...result.annotations, [question.question]: { notes: other } }
    }
    result.answers[question.question] = question.multiSelect ? chosen : (chosen[0] ?? '')
  }
  return result
}

/** Typed answers to secret questions are masked before the answer is shown or journaled. */
export function redactSecrets(questions: Question[], answers: QuestionAnswer[]): QuestionAnswer[] {
  return answers.map((answer) =>
    questions.find((question) => question.id === answer.questionId)?.secret && answer.other ? { ...answer, other: '••••' } : answer
  )
}

type ElicitationField = { type?: string; title?: string; description?: string; enum?: unknown[]; enumNames?: string[] }
export type ElicitationSchema = { properties?: Record<string, ElicitationField>; required?: string[] }

function choices(field: ElicitationField): unknown[] | undefined {
  return field.enum ?? (field.type === 'boolean' ? [true, false] : undefined)
}

/** An MCP elicitation form as questions: enums and booleans become options; other fields take typed text. */
export function elicitationQuestions(schema: ElicitationSchema): Question[] {
  return Object.entries(schema.properties ?? {}).map(([key, field]) => {
    const options = choices(field)
    return {
      id: key,
      header: field.title ?? key,
      question: field.description ?? field.title ?? key,
      multiSelect: false,
      allowOther: !options,
      options: (options ?? []).map((value, index) => ({
        id: String(index),
        label: field.enumNames?.[index] ?? (typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value))
      }))
    }
  })
}

/** The answers as the typed object the MCP server asked for. */
export function elicitationContent(schema: ElicitationSchema, questions: Question[], answers: QuestionAnswer[]): Record<string, unknown> {
  const content: Record<string, unknown> = {}
  for (const question of questions) {
    const field = schema.properties?.[question.id] ?? {}
    const answer = answerFor(question, answers)
    const options = choices(field)
    if (options) {
      const index = Number(answer?.optionIds[0])
      if (!Number.isNaN(index)) content[question.id] = options[index]
    } else if (answer?.other?.trim()) {
      const text = answer.other.trim()
      content[question.id] = field.type === 'number' || field.type === 'integer' ? Number(text) : text
    }
  }
  return content
}
