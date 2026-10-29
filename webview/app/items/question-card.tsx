import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Question, QuestionItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'
import { send } from '../host'
import { allAnswered, type Draft, isAnswered, pick, setOther, toAnswers } from './question-state'

/** A single-select pick shows as chosen briefly before the card moves on. */
const ADVANCE_MS = 200

function respondAnswers(item: QuestionItem, draft: Draft): void {
  send({ type: 'answer', itemId: item.id, response: { kind: 'answers', answers: toAnswers(item.questions, draft) } })
}

function dismiss(item: QuestionItem): void {
  send({ type: 'answer', itemId: item.id, response: { kind: 'dismiss' } })
}

export function QuestionCard({ item }: { item: QuestionItem }) {
  return item.resolved === undefined ? <PendingQuestion item={item} /> : <ResolvedQuestion item={item} />
}

function PendingQuestion({ item }: { item: QuestionItem }) {
  const [draft, setDraft] = useState<Draft>({})
  const [step, setStep] = useState(0)
  const card = useRef<HTMLDivElement>(null)
  const question = item.questions[step]
  const last = step === item.questions.length - 1

  const choose = (optionId: string) => {
    const next = pick(draft, question, optionId)
    setDraft(next)
    if (question.multiSelect) return
    if (!last) setTimeout(() => setStep((index) => index + 1), ADVANCE_MS)
    else if (allAnswered(item.questions, next)) respondAnswers(item, next)
  }

  // Number keys pick an option and Escape skips, unless the user is typing.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('textarea, input, [contenteditable="true"]') || event.metaKey || event.ctrlKey || event.altKey) return
      if (/^[1-9]$/.test(event.key)) {
        const option = question?.options[Number(event.key) - 1]
        if (!option) return
        event.preventDefault()
        choose(option.id)
      } else if (event.key === 'Escape') {
        event.preventDefault()
        dismiss(item)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (!question) return null
  const answer = draft[question.id]
  const preview = !question.multiSelect ? question.options.find((option) => answer?.optionIds.includes(option.id))?.preview : undefined

  return (
    <div ref={card} className="space-y-2.5 rounded-lg border border-info/50 bg-info/5 p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Codicon name="question" className="text-info" />
        <span className="min-w-0 flex-1 truncate">{item.title ?? 'Question'}</span>
        {question.header && <span className="rounded-full border px-1.5 py-0.5 text-[10px]">{question.header}</span>}
        {item.questions.length > 1 && (
          <span>
            {step + 1} of {item.questions.length}
          </span>
        )}
      </div>
      <div className="font-medium">{question.question}</div>
      {question.options.length > 0 && (
        <div className="space-y-1" role="listbox" aria-multiselectable={question.multiSelect}>
          {question.options.map((option, index) => {
            const selected = answer?.optionIds.includes(option.id) ?? false
            return (
              <button
                key={option.id}
                type="button"
                aria-pressed={selected}
                className={cn(
                  'flex w-full items-start gap-2 rounded-md border px-2.5 py-1.5 text-left text-sm hover:bg-accent',
                  selected && 'border-ring bg-accent'
                )}
                onClick={() => choose(option.id)}
              >
                <span className="mt-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded border text-[10px] text-muted-foreground">
                  {question.multiSelect && selected ? <Codicon name="check" size={10} /> : index + 1}
                </span>
                <span className="min-w-0">
                  <span className="block">{option.label}</span>
                  {option.description && <span className="block text-xs text-muted-foreground">{option.description}</span>}
                </span>
              </button>
            )
          })}
        </div>
      )}
      {preview && <pre className="max-h-48 overflow-auto rounded-md bg-code px-3 py-2 text-xs whitespace-pre-wrap">{preview}</pre>}
      {question.allowOther && (
        <input
          type={question.secret ? 'password' : 'text'}
          value={answer?.other ?? ''}
          placeholder={question.options.length > 0 ? 'Or type your answer' : 'Type your answer'}
          className="w-full rounded-md border bg-input px-2.5 py-1.5 text-sm outline-none focus:border-ring"
          onChange={(event) => setDraft(setOther(draft, question, event.target.value))}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' || !isAnswered(draft[question.id])) return
            event.preventDefault()
            if (!last) setStep(step + 1)
            else if (allAnswered(item.questions, draft)) respondAnswers(item, draft)
          }}
        />
      )}
      <div className="flex items-center gap-2">
        <Button size="sm" variant="ghost" onClick={() => dismiss(item)}>
          Skip
          <kbd className="ml-1 rounded border border-current/30 px-1 text-[10px] leading-4 opacity-80">esc</kbd>
        </Button>
        <span className="flex-1" />
        {step > 0 && (
          <Button size="sm" variant="secondary" onClick={() => setStep(step - 1)}>
            Back
          </Button>
        )}
        {last ? (
          <Button size="sm" disabled={!allAnswered(item.questions, draft)} onClick={() => respondAnswers(item, draft)}>
            Submit
          </Button>
        ) : (
          <Button size="sm" disabled={!isAnswered(answer)} onClick={() => setStep(step + 1)}>
            Next
          </Button>
        )}
      </div>
    </div>
  )
}

function answerText(question: Question, optionIds: string[], other?: string): string {
  const labels = optionIds.flatMap((id) => question.options.find((option) => option.id === id)?.label ?? [])
  return [...labels, ...(other?.trim() ? [other.trim()] : [])].join(', ')
}

function ResolvedQuestion({ item }: { item: QuestionItem }) {
  if (item.resolved === 'dismissed' || item.resolved === 'expired') {
    return (
      <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
        <Codicon name="question" size={12} />
        <span className="truncate">{item.questions[0]?.question ?? item.title}</span>
        <span>· {item.resolved === 'dismissed' ? 'Skipped' : 'Expired'}</span>
      </div>
    )
  }
  const answers = item.resolved?.answers ?? []
  return (
    <div className="space-y-0.5 px-1 text-xs text-muted-foreground">
      {item.questions.map((question) => {
        const answer = answers.find((entry) => entry.questionId === question.id)
        return (
          <div key={question.id} className="flex items-baseline gap-2">
            <Codicon name="question" size={12} />
            <span className="truncate">{question.question}</span>
            <span className="text-foreground">→ {answer ? answerText(question, answer.optionIds, answer.other) : '—'}</span>
          </div>
        )
      })}
    </div>
  )
}
