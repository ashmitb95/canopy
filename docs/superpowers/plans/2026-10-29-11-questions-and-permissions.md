# Plan 11: Questions, plan review, and permissions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. Plans 1–10 are complete.

**Goal:** Agents can ask the user questions and present plans for approval, and approvals carry everything needed to decide, for Claude, Codex, and Grok. Today Claude's AskUserQuestion is refused, Codex's question and permission requests are rejected, and Grok's questions and plan approvals fail.

**Architecture (modelled on Orca):** Two prompt items. **Approvals** (a decision among options; may carry a **plan** subject, a reason, and links to the diff items they would apply) and **questions** (1–4 questions, each with options, multi-select, free-text "Other", and secret input). The user's reply is one of three shapes: `{ kind: 'option', optionId }`, `{ kind: 'answers', answers }` (one per question: chosen option ids plus optional text), or `{ kind: 'dismiss' }`. Dismissing has meaning: for a question or plan it tells the agent to end its turn and wait. Each provider holds its pending prompts in a shared `PromptHolder` and encodes replies in its own wire format. Claude gains its native **Auto** permission mode, and approving a plan switches to the mode the user picks.

**Tech Stack:** as before.

**Verified before writing** (2026-10-29):
- **Claude** (Agent SDK `sdk-tools.d.ts`): `AskUserQuestion` input is `{ questions: [{ question, header, options: [{ label, description, preview? }] (2–4), multiSelect }] (1–4) }`; it is answered by allowing the tool with `updatedInput: { ...input, answers: { [question text]: answer } }` (multi-select answers comma-separated; an "Other" free text is always allowed). `ExitPlanMode` input carries `plan` (and in practice `planFilePath`). `PermissionUpdate` includes `{ type: 'setMode', mode, destination: 'session' }`; SDK `PermissionMode` includes `'auto'`. `canUseTool` context carries `title`, `description`, `decisionReason`, `blockedPath`, `suggestions`, `toolUseID`, `signal`.
- **Codex** (app-server schema, 0.165): `item/tool/requestUserInput { itemId, questions: [{ id, header, question, isOther, isSecret, options: [{ label, description }] | null }] }` → reply `{ answers: { [questionId]: { answers: string[] } } }`. `item/permissions/requestApproval { itemId, reason, permissions: { network: { enabled } | null, fileSystem: { read, write } | null } }` → reply `{ permissions: <granted subset>, scope: 'turn' | 'session' }`. `mcpServer/elicitation/request { serverName, mode: 'form' | 'url', message, requestedSchema | url }` → reply `{ action: 'accept' | 'decline' | 'cancel', content, _meta }`.
- **Grok** (AFK Pilot `research/ask-user-question.md`, `research/grok-build-oss-findings.md`; Orca `acp-dialects/grok-requests.ts`): `x.ai/ask_user_question` (also `_x.ai/…`) `{ sessionId, toolCallId, questions: [{ question, multiSelect?, options: [{ label, description?, preview? }] }] }` → reply `{ outcome: 'accepted', answers: { [question text]: label | labels[] }, annotations?: { [question text]: { notes } } }` or `{ outcome: 'cancelled' }`; "Other" text sends the label `Other` plus a note. `x.ai/exit_plan_mode` `{ toolCallId, planContent }` → reply (a JSON-RPC *result*, never an error) `{ outcome: 'approved' | 'cancelled' (keep planning) | 'abandoned' }`.
- Orca's dismissal messages: questions — "The user dismissed these questions without answering. End your turn and wait for them."; plans — "The user dismissed this plan without approving it. End your turn and wait for them to say what to change."; keep planning — "The user asked you to keep planning. Revise the plan and call ExitPlanMode again."

---

## File structure

| File | Responsibility |
|---|---|
| `src/core/types.ts` | `QuestionItem`, `Question`, `QuestionAnswer`, `PromptResponse`, approval fields, `auto` mode, `answer(itemId, response)` |
| `src/providers/prompt-holder.ts` | Pending prompts: show, settle once, dismiss all |
| `src/providers/prompts.ts` | Answer encoders per provider; MCP elicitation forms as questions; secret redaction |
| `src/providers/claude/provider.ts` | Questions, plan review, richer approvals, session-scoped allow, Auto mode |
| `src/providers/codex/{provider,translate}.ts` | User input, extra permissions, MCP elicitation, diff links |
| `src/providers/acp/{provider,translate}.ts` | Grok questions and plan review, diff links |
| `src/sessions/manager.ts` | Questions count as needing input; mode facts update the record |
| `src/ui/protocol.ts`, `src/ui/chat-surfaces.ts` | `answer` carries a `PromptResponse` |
| `webview/app/items/question-card.tsx`, `question-state.ts`, `approval-card.tsx`, `item-view.tsx` | The cards |
| `webview/app/components/mode-picker.tsx` | Auto mode label |
| `scripts/smoke-prompts.ts` | Live check: a real question and a real plan approval |

---

### Task 1: Types and the manager

**Files:**
- Modify: `src/core/types.ts`, `src/sessions/manager.ts`, `test/fake-provider.ts`, `test/sessions/manager.test.ts`

- [ ] **Step 1: Update the tests first**

In `test/fake-provider.ts`:
- import `PromptResponse` with the other core types;
- change `readonly answers: [string, string][] = []` to `readonly answers: [string, PromptResponse][] = []`;
- change the `answer` method to:

```ts
  answer(itemId: string, response: PromptResponse): void {
    this.answers.push([itemId, response])
  }
```

In `test/sessions/manager.test.ts`:
- in *needs input while an approval is pending and forwards the answer*, change `manager.answer(id, 'approval:1', 'allow')` to `manager.answer(id, 'approval:1', { kind: 'option', optionId: 'allow' })` and the expectation to `expect(sessions[0].answers).toEqual([['approval:1', { kind: 'option', optionId: 'allow' }]])`;
- add inside the `describe` block:

```ts
  it('needs input while a question is pending and resumes once it is answered', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('ask me'))
    const question: SessionItem = {
      kind: 'question',
      id: 'question:1',
      questions: [{ id: 'q1', question: 'Which color?', multiSelect: false, allowOther: true, options: [{ id: 'o1', label: 'Red' }] }]
    }
    sessions[0].emit(question)
    expect(manager.list()[0].status).toBe('needs-input')
    sessions[0].emit({ ...question, resolved: { answers: [{ questionId: 'q1', optionIds: ['o1'] }] } } as SessionItem)
    expect(manager.list()[0].status).toBe('running')
  })

  it('records the permission mode a provider switches to', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.warm(id)
    sessions[0].fact({ kind: 'mode', current: 'accept-edits', available: ['ask', 'accept-edits'] })
    expect(manager.list()[0].record.mode).toBe('accept-edits')
  })
```

  (add `SessionItem` to the test's type import from `../../src/core/types`);
- in *expires approvals and finishes streams left over from a previous run*, add a pending question line to the journal written before reload and expect it back with `resolved: 'expired'`: add to the written lines `JSON.stringify({ kind: 'question', id: 'question:old', questions: [] })` (after the approval line) and to the expected `snapshot.items`, after the approval, `{ kind: 'question', id: 'question:old', questions: [], resolved: 'expired' }`.

Run: `pnpm test test/sessions/manager.test.ts` → FAIL (types aside, the question does not set needs-input and the mode is not recorded).

- [ ] **Step 2: Types**

In `src/core/types.ts`:
- replace the `ApprovalOption` and `ApprovalItem` declarations with:

```ts
export type ApprovalOption = { id: string; label: string }

/** What an approval is about, beyond a tool call: a plan to accept before the agent builds. */
export type ApprovalSubject = { kind: 'plan'; text: string; filePath?: string }

export type ApprovalItem = {
  kind: 'approval'
  id: string
  title: string
  detail?: string
  /** Extra context from the provider, e.g. what the tool will be able to do. */
  description?: string
  /** Why the provider is asking, e.g. a blocked path or a matched rule. */
  reason?: string
  subject?: ApprovalSubject
  /** Diff items this approval would apply, for Review changes. */
  diffIds?: string[]
  options: ApprovalOption[]
  /** The chosen option id, `dismissed`, or `expired`. */
  resolved?: string
}

export type PromptOption = { id: string; label: string; description?: string; preview?: string }

export type Question = {
  id: string
  header?: string
  question: string
  options: PromptOption[]
  multiSelect: boolean
  /** Whether a typed answer is accepted besides the options. */
  allowOther: boolean
  /** A typed answer is a secret: masked while typing and never stored. */
  secret?: boolean
}

export type QuestionAnswer = { questionId: string; optionIds: string[]; other?: string }

export type QuestionItem = {
  kind: 'question'
  id: string
  title?: string
  questions: Question[]
  resolved?: { answers: QuestionAnswer[] } | 'dismissed' | 'expired'
}

/** The user's reply to an approval or a question. */
export type PromptResponse =
  | { kind: 'option'; optionId: string }
  | { kind: 'answers'; answers: QuestionAnswer[] }
  | { kind: 'dismiss' }
```

- add `| QuestionItem` to the `SessionItem` union (after `ApprovalItem`);
- change `PermissionMode` to `export type PermissionMode = 'ask' | 'accept-edits' | 'auto' | 'plan' | 'full-access'`;
- in `ProviderSession`, change the `answer` doc comment and signature to:

```ts
  /** Settles a pending approval or question. */
  answer(itemId: string, response: PromptResponse): void
```

- [ ] **Step 3: Manager**

In `src/sessions/manager.ts`:
- import `PromptResponse` with the core types;
- rename the `Live` field `approvals: Set<string>` to `prompts: Set<string>` (and every use: `load`, `turnEnded`, `fail`, the former `approvalChanged`);
- change `answer` to:

```ts
  answer(id: string, itemId: string, response: PromptResponse): void {
    this.live.get(id)?.session?.answer(itemId, response)
  }
```

- in `upsert`, replace the approval line with:

```ts
    if (item.kind === 'approval' || item.kind === 'question') this.promptChanged(live, item.id, item.resolved !== undefined)
```

- replace `approvalChanged` with:

```ts
  private promptChanged(live: Live, id: string, resolved: boolean): void {
    if (!resolved) {
      live.prompts.add(id)
      this.setStatus(live, 'needs-input')
      this.attention.fire({ sessionId: live.record.id, reason: 'needs-input' })
      return
    }
    live.prompts.delete(id)
    if (live.prompts.size === 0 && live.status === 'needs-input') this.setStatus(live, 'running')
  }
```

- in `fact`, add as the first line: `if (fact.kind === 'mode') live.record.mode = fact.current`;
- in `settled`, change the approval line to:

```ts
  if ((item.kind === 'approval' || item.kind === 'question') && item.resolved === undefined) return { ...item, resolved: 'expired' }
```

Run: `pnpm test test/sessions` → PASS. (`pnpm typecheck` fails in the providers and webview until Tasks 3–6; that is expected.)

- [ ] **Step 4: Commit**

```bash
git add src/core/types.ts src/sessions/manager.ts test
git commit -m "feat(core): question items, prompt responses, and the Auto mode"
```

---

### Task 2: Prompt holder and answer encoders

**Files:**
- Create: `src/providers/prompt-holder.ts`, `src/providers/prompts.ts`
- Test: `test/providers/prompt-holder.test.ts`, `test/providers/prompts.test.ts`

- [ ] **Step 1: Write the failing tests**

`test/providers/prompt-holder.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { ApprovalItem, SessionItem } from '../../src/core/types'
import { PromptHolder } from '../../src/providers/prompt-holder'

const approval: ApprovalItem = { kind: 'approval', id: 'a1', title: 'Allow?', options: [{ id: 'allow', label: 'Allow' }] }

describe('PromptHolder', () => {
  it('shows a prompt, settles it once, and shows how it was resolved', async () => {
    const emitted: SessionItem[] = []
    const holder = new PromptHolder((item) => emitted.push(item))
    const result = holder.hold(approval, (response) => ({
      resolved: response.kind === 'option' ? response.optionId : 'dismissed',
      result: response.kind
    }))
    holder.answer('a1', { kind: 'option', optionId: 'allow' })
    holder.answer('a1', { kind: 'dismiss' })
    await expect(result).resolves.toBe('option')
    expect(emitted).toEqual([approval, { ...approval, resolved: 'allow' }])
  })

  it('dismisses everything still pending', async () => {
    const holder = new PromptHolder(() => {})
    const first = holder.hold(approval, (response) => ({ resolved: 'x', result: response.kind }))
    const second = holder.hold({ ...approval, id: 'a2' }, (response) => ({ resolved: 'x', result: response.kind }))
    holder.dismissAll()
    await expect(Promise.all([first, second])).resolves.toEqual(['dismiss', 'dismiss'])
  })
})
```

`test/providers/prompts.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { Question } from '../../src/core/types'
import {
  claudeAnswers,
  codexAnswers,
  elicitationContent,
  elicitationQuestions,
  grokAnswers,
  redactSecrets
} from '../../src/providers/prompts'

const color: Question = {
  id: 'q1',
  question: 'Which color?',
  multiSelect: false,
  allowOther: true,
  options: [
    { id: 'o1', label: 'Red' },
    { id: 'o2', label: 'Blue' }
  ]
}
const sizes: Question = {
  id: 'q2',
  question: 'Which sizes?',
  multiSelect: true,
  allowOther: true,
  options: [
    { id: 'o1', label: 'S' },
    { id: 'o2', label: 'M' }
  ]
}

describe('answer encoders', () => {
  it('encodes Claude answers by question text, comma-joining multi-select and adding typed text', () => {
    expect(
      claudeAnswers(
        [color, sizes],
        [
          { questionId: 'q1', optionIds: ['o2'] },
          { questionId: 'q2', optionIds: ['o1', 'o2'], other: 'XL' }
        ]
      )
    ).toEqual({ 'Which color?': 'Blue', 'Which sizes?': 'S, M, XL' })
  })

  it('encodes Codex answers by question id', () => {
    expect(codexAnswers([color], [{ questionId: 'q1', optionIds: [], other: 'Green' }])).toEqual({
      answers: { q1: { answers: ['Green'] } }
    })
  })

  it('encodes Grok answers with arrays for multi-select and typed text as an annotation', () => {
    expect(
      grokAnswers(
        [color, sizes],
        [
          { questionId: 'q1', optionIds: [], other: 'Green' },
          { questionId: 'q2', optionIds: ['o2'] }
        ]
      )
    ).toEqual({
      outcome: 'accepted',
      answers: { 'Which color?': 'Other', 'Which sizes?': ['M'] },
      annotations: { 'Which color?': { notes: 'Green' } }
    })
  })

  it('redacts typed answers to secret questions before they are stored', () => {
    const secret: Question = { ...color, id: 'q3', secret: true, options: [] }
    expect(redactSecrets([secret], [{ questionId: 'q3', optionIds: [], other: 'hunter2' }])).toEqual([
      { questionId: 'q3', optionIds: [], other: '••••' }
    ])
  })
})

describe('MCP elicitation forms', () => {
  const schema = {
    properties: {
      env: { type: 'string', title: 'Environment', enum: ['staging', 'prod'] },
      confirm: { type: 'boolean', description: 'Apply now?' },
      count: { type: 'integer', title: 'Count' },
      note: { type: 'string' }
    }
  }

  it('turns fields into questions', () => {
    expect(elicitationQuestions(schema)).toEqual([
      {
        id: 'env',
        header: 'Environment',
        question: 'Environment',
        multiSelect: false,
        allowOther: false,
        options: [
          { id: '0', label: 'staging' },
          { id: '1', label: 'prod' }
        ]
      },
      {
        id: 'confirm',
        header: 'confirm',
        question: 'Apply now?',
        multiSelect: false,
        allowOther: false,
        options: [
          { id: '0', label: 'Yes' },
          { id: '1', label: 'No' }
        ]
      },
      { id: 'count', header: 'Count', question: 'Count', multiSelect: false, allowOther: true, options: [] },
      { id: 'note', header: 'note', question: 'note', multiSelect: false, allowOther: true, options: [] }
    ])
  })

  it('turns answers back into typed content', () => {
    const questions = elicitationQuestions(schema)
    expect(
      elicitationContent(schema, questions, [
        { questionId: 'env', optionIds: ['1'] },
        { questionId: 'confirm', optionIds: ['0'] },
        { questionId: 'count', optionIds: [], other: '3' },
        { questionId: 'note', optionIds: [], other: 'ship it' }
      ])
    ).toEqual({ env: 'prod', confirm: true, count: 3, note: 'ship it' })
  })
})
```

Run: `pnpm test test/providers/prompt-holder.test.ts test/providers/prompts.test.ts` → FAIL (modules missing).

- [ ] **Step 2: Implement**

`src/providers/prompt-holder.ts`:

```ts
import type { ApprovalItem, PromptResponse, QuestionItem, SessionItem } from '../core/types'

type Reply<T> = { resolved: string | NonNullable<QuestionItem['resolved']>; result: T }

/** Pending approvals and questions: shows each as an item and settles it once with the user's response. */
export class PromptHolder {
  private readonly pending = new Map<string, (response: PromptResponse) => void>()

  constructor(private readonly emit: (item: SessionItem) => void) {}

  hold<T>(item: ApprovalItem | QuestionItem, reply: (response: PromptResponse) => Reply<T>): Promise<T> {
    return new Promise<T>((resolve) => {
      this.pending.set(item.id, (response) => {
        const { resolved, result } = reply(response)
        this.emit({ ...item, resolved } as SessionItem)
        resolve(result)
      })
      this.emit(item)
    })
  }

  answer(itemId: string, response: PromptResponse): void {
    const settle = this.pending.get(itemId)
    if (!settle) return
    this.pending.delete(itemId)
    settle(response)
  }

  dismissAll(): void {
    for (const itemId of [...this.pending.keys()]) this.answer(itemId, { kind: 'dismiss' })
  }
}
```

`src/providers/prompts.ts`:

```ts
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
```

Run: `pnpm test test/providers/prompt-holder.test.ts test/providers/prompts.test.ts` → PASS.

- [ ] **Step 3: Commit**

```bash
git add src/providers/prompt-holder.ts src/providers/prompts.ts test/providers/prompt-holder.test.ts test/providers/prompts.test.ts
git commit -m "feat(providers): prompt holder and per-provider answer encoders"
```

---

### Task 3: Claude

**Files:**
- Modify: `src/providers/claude/provider.ts`

- [ ] **Step 1: Modes**

- In `MODES`, add `auto: 'auto',` after `'accept-edits': 'acceptEdits',`.
- Change `MODE_LIST` to `['ask', 'accept-edits', 'auto', 'plan', 'full-access']`.

- [ ] **Step 2: Hold prompts in a `PromptHolder`**

- Add imports: `import { PromptHolder } from '../prompt-holder'` and `import { claudeAnswers } from '../prompts'`; add `PromptResponse`, `QuestionItem` to the core type import.
- Delete the `PendingApproval` type and the `approvals` field; add, after the `translator` field:

```ts
  private readonly holder = new PromptHolder((item) => this.items.fire(item))
```

- Replace `answer` with:

```ts
  answer(itemId: string, response: PromptResponse): void {
    this.holder.answer(itemId, response)
  }
```

- In `dispose`, replace the approvals loop with `this.holder.dismissAll()`.

- [ ] **Step 3: Questions, plans, and richer approvals**

Replace `requestApproval` with these methods, and add the two constants above the class:

```ts
const EDIT_TOOLS = new Set(['Edit', 'Write'])

const PLAN_OPTIONS = [
  { id: 'approve:ask', label: 'Approve · Ask before edits' },
  { id: 'approve:accept-edits', label: 'Approve · Accept edits' },
  { id: 'approve:auto', label: 'Approve · Auto' },
  { id: 'keep-planning', label: 'Keep planning' }
]
```

```ts
  private requestApproval(
    toolName: string,
    input: Record<string, unknown>,
    context: ApprovalContext
  ): Promise<PermissionResult> {
    const prompt =
      toolName === 'AskUserQuestion' ? this.question(input, context.toolUseID) : this.approval(toolName, input, context)
    context.signal.addEventListener('abort', () => this.holder.answer(`${toolName === 'AskUserQuestion' ? 'question' : 'approval'}:${context.toolUseID}`, { kind: 'dismiss' }))
    return prompt
  }

  private question(input: Record<string, unknown>, toolUseId: string): Promise<PermissionResult> {
    const raw = (Array.isArray(input.questions) ? input.questions : []) as {
      question: string
      header?: string
      multiSelect?: boolean
      options?: { label: string; description?: string; preview?: string }[]
    }[]
    const item: QuestionItem = {
      kind: 'question',
      id: `question:${toolUseId}`,
      questions: raw.map((question, index) => ({
        id: `q${index + 1}`,
        header: question.header,
        question: question.question,
        multiSelect: question.multiSelect === true,
        allowOther: true,
        options: (question.options ?? []).map((option, optionIndex) => ({
          id: `o${optionIndex + 1}`,
          label: option.label,
          description: option.description,
          preview: option.preview
        }))
      }))
    }
    return this.holder.hold(item, (response) =>
      response.kind === 'answers'
        ? {
            resolved: { answers: response.answers },
            // The CLI rejects an allow without updatedInput, although the SDK types mark it optional.
            result: { behavior: 'allow', updatedInput: { ...input, answers: claudeAnswers(item.questions, response.answers) } }
          }
        : {
            resolved: 'dismissed',
            result: {
              behavior: 'deny',
              message: 'The user dismissed these questions without answering. End your turn and wait for them.'
            }
          }
    )
  }

  private approval(toolName: string, input: Record<string, unknown>, context: ApprovalContext): Promise<PermissionResult> {
    const plan = toolName === 'ExitPlanMode' && typeof input.plan === 'string' ? input.plan : undefined
    const filePath = typeof input.planFilePath === 'string' ? input.planFilePath : undefined
    const suggestions = context.suppressAlwaysAllowRule ? [] : (context.suggestions ?? [])
    const reason = [context.decisionReason, context.blockedPath && `Path: ${context.blockedPath}`].filter(Boolean).join(' · ')
    const item: ApprovalItem = {
      kind: 'approval',
      id: `approval:${context.toolUseID}`,
      title: plan ? 'Ready to code?' : (context.title ?? `Allow ${toolName}?`),
      ...(plan ? { subject: { kind: 'plan' as const, text: plan, ...(filePath ? { filePath } : {}) } } : { detail: approvalDetail(input) }),
      ...(context.description ? { description: context.description } : {}),
      ...(reason ? { reason } : {}),
      ...(EDIT_TOOLS.has(toolName) ? { diffIds: [`${context.toolUseID}:diff`] } : {}),
      options: plan
        ? PLAN_OPTIONS
        : [
            { id: 'allow', label: 'Allow once' },
            ...(suggestions.length > 0 ? [{ id: 'allowForSession', label: 'Allow for this session' }] : []),
            { id: 'deny', label: 'Deny' }
          ]
    }
    return this.holder.hold(item, (response) => {
      const optionId = response.kind === 'option' ? response.optionId : 'dismissed'
      return { resolved: optionId, result: this.approvalResult(optionId, input, suggestions, plan !== undefined) }
    })
  }

  private approvalResult(
    optionId: string,
    input: Record<string, unknown>,
    suggestions: PermissionUpdate[],
    plan: boolean
  ): PermissionResult {
    if (optionId.startsWith('approve:')) {
      const mode = optionId.slice('approve:'.length) as PermissionMode
      this.facts.fire({ kind: 'mode', current: mode, available: MODE_LIST })
      return {
        behavior: 'allow',
        updatedInput: input,
        updatedPermissions: [{ type: 'setMode', mode: MODES[mode], destination: 'session' }]
      }
    }
    if (optionId === 'allow' || optionId === 'allowForSession') {
      // The CLI rejects an allow without updatedInput, although the SDK types mark it optional.
      return {
        behavior: 'allow',
        updatedInput: input,
        // "For this session": the CLI's own suggestion, kept to this session rather than written to settings.
        ...(optionId === 'allowForSession'
          ? { updatedPermissions: suggestions.map((suggestion) => ({ ...suggestion, destination: 'session' as const })) }
          : {})
      }
    }
    const message =
      optionId === 'keep-planning'
        ? 'The user asked you to keep planning. Revise the plan and call ExitPlanMode again.'
        : optionId === 'dismissed'
          ? plan
            ? 'The user dismissed this plan without approving it. End your turn and wait for them to say what to change.'
            : 'The user dismissed this request. End your turn and wait for them.'
          : 'The user denied this action.'
    return { behavior: 'deny', message }
  }
```

The `requestApproval` abort listener builds the item id the same way `question` and `approval` do; keep the two in step.

- [ ] **Step 4: Verify and commit**

Run: `pnpm typecheck` → errors only in `src/providers/codex`, `src/providers/acp`, `src/ui`, and `webview` (Tasks 4–6). Any error in `src/providers/claude`: fix it (types only) and report.

```bash
git add src/providers/claude/provider.ts
git commit -m "feat(claude): questions, plan review with a next mode, richer approvals, and Auto mode"
```

---

### Task 4: Codex

**Files:**
- Modify: `src/providers/codex/translate.ts`, `src/providers/codex/provider.ts`
- Test: `test/providers/codex-translate.test.ts` (one test added)

- [ ] **Step 1: Diff links, test first**

Add to `test/providers/codex-translate.test.ts`:

```ts
  it('remembers which diff items a file change produced', () => {
    const translator = new CodexTranslator(() => {})
    translator.feed('item/started', {
      item: {
        type: 'fileChange',
        id: 'f9',
        status: 'inProgress',
        changes: [
          { path: '/w/a.ts', kind: { type: 'update', move_path: null }, diff: '@@ -1 +1 @@\n-a\n+b' },
          { path: '/w/b.ts', kind: { type: 'add' }, diff: 'new' }
        ]
      }
    })
    expect(translator.diffIdsFor('f9')).toEqual(['f9:0', 'f9:1'])
    expect(translator.diffIdsFor('missing')).toEqual([])
  })
```

Run → FAIL. In `src/providers/codex/translate.ts`, add a field `private readonly diffs = new Map<string, string[]>()`, in the `fileChange` case add `this.diffs.set(item.id, item.changes.map((_, index) => `${item.id}:${index}`))` before the `forEach`, and add:

```ts
  /** The diff items a file change produced, so its approval can offer Review changes. */
  diffIdsFor(itemId: string): string[] {
    return this.diffs.get(itemId) ?? []
  }
```

Run → PASS.

- [ ] **Step 2: Provider**

In `src/providers/codex/provider.ts`:
- imports: `import { randomUUID } from 'node:crypto'`; `import { PromptHolder } from '../prompt-holder'`; `import { codexAnswers, elicitationContent, elicitationQuestions, type ElicitationSchema, redactSecrets } from '../prompts'`; add `PromptResponse`, `Question`, `QuestionItem` to the core type import;
- replace the `approvals` field with `private readonly holder = new PromptHolder((item) => this.items.fire(item))`;
- replace `answer` with `answer(itemId: string, response: PromptResponse): void { this.holder.answer(itemId, response) }`;
- in `dispose`, replace the approvals loop with `this.holder.dismissAll()`;
- replace `serverRequest` and `ask` with:

```ts
  private serverRequest({ method, params }: ServerRequest): Promise<unknown> {
    switch (method) {
      case 'item/commandExecution/requestApproval': {
        const request = params as { itemId: string; command?: string | null; reason?: string | null }
        const detail = request.command ? unwrapShell(request.command) : (request.reason ?? undefined)
        return this.decision(request.itemId, 'Allow Codex to run this command?', detail, [])
      }
      case 'item/fileChange/requestApproval': {
        const request = params as { itemId: string; reason?: string | null; grantRoot?: string | null }
        if (this.mode === 'accept-edits') return Promise.resolve({ decision: 'accept' })
        const detail = request.grantRoot ?? request.reason ?? undefined
        return this.decision(request.itemId, 'Allow Codex to change files?', detail, this.translator.diffIdsFor(request.itemId))
      }
      case 'item/tool/requestUserInput':
        return this.userInput(params as UserInputRequest)
      case 'item/permissions/requestApproval':
        return this.permissions(params as PermissionsRequest)
      case 'mcpServer/elicitation/request':
        return this.elicitation(params as ElicitationRequest)
      default:
        return Promise.reject(new Error(`AgentDeck does not handle ${method} yet.`))
    }
  }

  private decision(itemId: string, title: string, detail: string | undefined, diffIds: string[]): Promise<{ decision: string }> {
    const item: ApprovalItem = {
      kind: 'approval',
      id: `approval:${itemId}`,
      title,
      detail,
      ...(diffIds.length > 0 ? { diffIds } : {}),
      options: [
        { id: 'allow', label: 'Allow once' },
        { id: 'allowForSession', label: 'Allow for this session' },
        { id: 'deny', label: 'Deny' }
      ]
    }
    return this.holder.hold(item, (response) => {
      const optionId = response.kind === 'option' ? response.optionId : 'dismissed'
      const decision = optionId === 'allow' ? 'accept' : optionId === 'allowForSession' ? 'acceptForSession' : 'decline'
      return { resolved: optionId, result: { decision } }
    })
  }

  private userInput(request: UserInputRequest): Promise<unknown> {
    const questions: Question[] = request.questions.map((question) => ({
      id: question.id,
      header: question.header,
      question: question.question,
      multiSelect: false,
      allowOther: question.isOther || !question.options?.length,
      ...(question.isSecret ? { secret: true } : {}),
      options: (question.options ?? []).map((option, index) => ({ id: `o${index + 1}`, label: option.label, description: option.description }))
    }))
    const item: QuestionItem = { kind: 'question', id: `question:${request.itemId}`, questions }
    return this.holder.hold(item, (response) =>
      response.kind === 'answers'
        ? { resolved: { answers: redactSecrets(questions, response.answers) }, result: codexAnswers(questions, response.answers) }
        : { resolved: 'dismissed', result: { answers: {} } }
    )
  }

  private permissions(request: PermissionsRequest): Promise<unknown> {
    const { fileSystem, network } = request.permissions
    const lines = [
      ...(fileSystem?.write ?? []).map((path) => `Write ${path}`),
      ...(fileSystem?.read ?? []).map((path) => `Read ${path}`),
      ...(network?.enabled ? ['Network access'] : [])
    ]
    const item: ApprovalItem = {
      kind: 'approval',
      id: `approval:${request.itemId}:permissions`,
      title: 'Allow Codex more access?',
      detail: lines.join('\n'),
      ...(request.reason ? { reason: request.reason } : {}),
      options: [
        { id: 'allow', label: 'Allow for this turn' },
        { id: 'allowForSession', label: 'Allow for this session' },
        { id: 'deny', label: 'Deny' }
      ]
    }
    return this.holder.hold(item, (response) => {
      const optionId = response.kind === 'option' ? response.optionId : 'dismissed'
      const granted = optionId === 'allow' || optionId === 'allowForSession'
      return {
        resolved: optionId,
        result: {
          permissions: granted ? { ...(network ? { network } : {}), ...(fileSystem ? { fileSystem } : {}) } : {},
          scope: optionId === 'allowForSession' ? 'session' : 'turn'
        }
      }
    })
  }

  private elicitation(request: ElicitationRequest): Promise<unknown> {
    const id = `elicitation:${randomUUID()}`
    if (request.mode === 'url') {
      const item: ApprovalItem = {
        kind: 'approval',
        id,
        title: `${request.serverName} asks you to open a link`,
        description: request.message,
        detail: request.url,
        options: [
          { id: 'allow', label: 'Done' },
          { id: 'deny', label: 'Decline' }
        ]
      }
      return this.holder.hold(item, (response) => {
        const optionId = response.kind === 'option' ? response.optionId : 'dismissed'
        return { resolved: optionId, result: { action: optionId === 'allow' ? 'accept' : 'decline', content: null, _meta: null } }
      })
    }
    const schema = request.requestedSchema as ElicitationSchema
    const questions = elicitationQuestions(schema)
    const item: QuestionItem = { kind: 'question', id, title: `${request.serverName}: ${request.message}`, questions }
    return this.holder.hold(item, (response) =>
      response.kind === 'answers'
        ? {
            resolved: { answers: response.answers },
            result: { action: 'accept', content: elicitationContent(schema, questions, response.answers), _meta: null }
          }
        : { resolved: 'dismissed', result: { action: 'decline', content: null, _meta: null } }
    )
  }
```

and add these types near the top of the file:

```ts
type UserInputRequest = {
  itemId: string
  questions: {
    id: string
    header: string
    question: string
    isOther: boolean
    isSecret: boolean
    options: { label: string; description: string }[] | null
  }[]
}

type PermissionsRequest = {
  itemId: string
  reason: string | null
  permissions: {
    network: { enabled: boolean | null } | null
    fileSystem: { read: string[] | null; write: string[] | null } | null
  }
}

type ElicitationRequest = { serverName: string; message: string } & (
  | { mode: 'url'; url: string }
  | { mode: 'form' | 'openai/form' | 'openaiForm'; requestedSchema: unknown }
)
```

- [ ] **Step 3: Verify and commit**

Run: `pnpm test` (Codex tests) and `pnpm typecheck` → errors only outside `src/providers/codex` (Tasks 5–6).

```bash
git add src/providers/codex test/providers/codex-translate.test.ts
git commit -m "feat(codex): questions, extra-access approvals, MCP forms and links, and diff links on approvals"
```

---

### Task 5: Grok (ACP)

**Files:**
- Modify: `src/providers/acp/translate.ts`, `src/providers/acp/provider.ts`
- Test: `test/providers/acp-translate.test.ts` (one test added)

- [ ] **Step 1: Diff links, test first**

Add to `test/providers/acp-translate.test.ts`:

```ts
  it('remembers which diff items a tool call produced', () => {
    const translator = new AcpTranslator(() => {})
    translator.startTurn()
    translator.feed({
      sessionUpdate: 'tool_call_update',
      toolCallId: 't7',
      kind: 'edit',
      status: 'pending',
      content: [{ type: 'diff', path: '/w/a.md', oldText: 'a', newText: 'b' }]
    })
    expect(translator.diffIdsFor('t7')).toEqual(['t7:diff:0'])
    expect(translator.diffIdsFor('nope')).toEqual([])
  })
```

Run → FAIL. In `src/providers/acp/translate.ts`: add `private readonly diffs = new Map<string, string[]>()`; in `tool`, inside the `forEach` over `update.content`, after the `if (block.type !== 'diff') return`, add `this.diffs.set(update.toolCallId, [...new Set([...(this.diffs.get(update.toolCallId) ?? []), `${update.toolCallId}:diff:${index}`])])`; and add:

```ts
  /** The diff items a tool call produced, so its approval can offer Review changes. */
  diffIdsFor(toolCallId: string): string[] {
    return this.diffs.get(toolCallId) ?? []
  }
```

Run → PASS.

- [ ] **Step 2: Provider**

In `src/providers/acp/provider.ts`:
- imports: `import { PromptHolder } from '../prompt-holder'`, `import { grokAnswers } from '../prompts'`; add `PromptResponse`, `Question`, `QuestionItem` to the core type import;
- replace the `approvals` field with `private readonly holder = new PromptHolder((item) => this.items.fire(item))`;
- replace `answer` with `answer(itemId: string, response: PromptResponse): void { this.holder.answer(itemId, response) }`;
- in `cancel` and `dispose`, replace the approvals loops with `this.holder.dismissAll()`; delete `settle`;
- replace `serverRequest` with:

```ts
  private serverRequest({ method, params }: ServerRequest): Promise<unknown> {
    // Grok's extensions arrive with or without a leading underscore.
    const name = method.replace(/^_/, '')
    if (name === 'session/request_permission') return this.permission(params as PermissionRequest)
    if (name === 'x.ai/ask_user_question') return this.question(params as AgentQuestionRequest)
    if (name === 'x.ai/exit_plan_mode') return this.plan(params as AgentPlanRequest)
    return Promise.reject(new Error(`AgentDeck does not handle ${method}.`))
  }
```

- in `permission`, change the option table entry `['allow_always', 'always', undefined]` to `['allow_always', 'allowForSession', undefined]`, add `...(this.translator.diffIdsFor(toolCall.toolCallId).length > 0 ? { diffIds: this.translator.diffIdsFor(toolCall.toolCallId) } : {})` to the item, and replace its `return new Promise(…)` with:

```ts
    return this.holder.hold(item, (response) => {
      const optionId = response.kind === 'option' ? response.optionId : 'dismissed'
      const chosen = optionIds.get(optionId)
      return { resolved: optionId, result: chosen ? selected(chosen) : CANCELLED }
    })
```

- add:

```ts
  private question(request: AgentQuestionRequest): Promise<unknown> {
    const questions: Question[] = request.questions.map((question, index) => ({
      id: `q${index + 1}`,
      question: question.question,
      multiSelect: question.multiSelect === true,
      allowOther: true,
      options: question.options.map((option, optionIndex) => ({
        id: `o${optionIndex + 1}`,
        label: option.label,
        description: option.description ?? undefined,
        preview: option.preview ?? undefined
      }))
    }))
    const item: QuestionItem = { kind: 'question', id: `question:${request.toolCallId}`, questions }
    return this.holder.hold(item, (response) =>
      response.kind === 'answers'
        ? { resolved: { answers: response.answers }, result: grokAnswers(questions, response.answers) }
        : { resolved: 'dismissed', result: { outcome: 'cancelled' } }
    )
  }

  /** Grok treats any error reply as a disconnected client, so every verdict is a result. */
  private plan(request: AgentPlanRequest): Promise<unknown> {
    const item: ApprovalItem = {
      kind: 'approval',
      id: `approval:plan:${request.toolCallId}`,
      title: 'Ready to build?',
      subject: { kind: 'plan', text: request.planContent ?? request.plan ?? '' },
      options: [
        { id: 'approve', label: 'Approve' },
        { id: 'keep-planning', label: 'Keep planning' }
      ]
    }
    return this.holder.hold(item, (response) => {
      const optionId = response.kind === 'option' ? response.optionId : 'dismissed'
      const outcome = optionId === 'approve' ? 'approved' : optionId === 'keep-planning' ? 'cancelled' : 'abandoned'
      return { resolved: optionId, result: { outcome } }
    })
  }
```

- add types near the top:

```ts
type AgentQuestionRequest = {
  toolCallId: string
  questions: {
    question: string
    multiSelect?: boolean | null
    options: { label: string; description?: string | null; preview?: string | null }[]
  }[]
}

type AgentPlanRequest = { toolCallId: string; planContent?: string | null; plan?: string | null }
```

- [ ] **Step 3: Verify and commit**

Run: `pnpm test` → PASS; `pnpm typecheck` → errors only in `src/ui` and `webview` (Task 6).

```bash
git add src/providers/acp test/providers/acp-translate.test.ts
git commit -m "feat(acp): Grok questions and plan review; diff links on approvals"
```

---

### Task 6: Protocol and host

**Files:**
- Modify: `src/ui/protocol.ts`, `src/ui/chat-surfaces.ts`

- [ ] **Step 1:** In `src/ui/protocol.ts`, import `PromptResponse` with the core types and change `| { type: 'answer'; itemId: string; optionId: string }` to `| { type: 'answer'; itemId: string; response: PromptResponse }`.

- [ ] **Step 2:** In `src/ui/chat-surfaces.ts`, change the `'answer'` case to `if (sessionId) this.manager.answer(sessionId, message.itemId, message.response)`, and in `attend` change the message text `needs your approval` to `needs your input`.

- [ ] **Step 3:** Run `pnpm typecheck` → errors only in `webview` (Task 7). Commit:

```bash
git add src/ui
git commit -m "feat(ui): carry prompt responses from the webview to providers"
```

---

### Task 7: Cards

**Files:**
- Create: `webview/app/items/question-state.ts`, `webview/app/items/question-card.tsx`
- Modify: `webview/app/items/approval-card.tsx` (full replacement), `webview/app/items/item-view.tsx`, `webview/app/components/mode-picker.tsx`
- Test: `test/webview/question-state.test.ts`

- [ ] **Step 1: Write the failing test**

`test/webview/question-state.test.ts`:

```ts
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
```

Run → FAIL.

- [ ] **Step 2: Question state**

`webview/app/items/question-state.ts`:

```ts
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
```

Run → PASS.

- [ ] **Step 3: Question card**

`webview/app/items/question-card.tsx`:

```tsx
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
```

- [ ] **Step 4: Approval card**

`webview/app/items/approval-card.tsx` (full replacement):

```tsx
import { useEffect } from 'react'
import { MessageResponse } from '@/components/ai-elements/message'
import { Button } from '@/components/ui/button'
import type { ApprovalItem, PromptResponse, SessionItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'
import { send } from '../host'

function respond(item: ApprovalItem, response: PromptResponse): void {
  send({ type: 'answer', itemId: item.id, response })
}

const choose = (item: ApprovalItem, optionId: string) => respond(item, { kind: 'option', optionId })

function Kbd({ children }: { children: string }) {
  return <kbd className="ml-1 rounded border border-current/30 px-1 text-[10px] leading-4 opacity-80">{children}</kbd>
}

function resolvedLabel(item: ApprovalItem): string {
  if (item.resolved === 'expired') return 'Expired'
  if (item.resolved === 'dismissed') return 'Dismissed'
  return item.options.find((option) => option.id === item.resolved)?.label ?? item.resolved ?? ''
}

export function ApprovalCard({ item }: { item: ApprovalItem }) {
  if (item.resolved) {
    return (
      <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
        <Codicon name={item.subject?.kind === 'plan' ? 'checklist' : 'shield'} size={12} />
        <span className="truncate">{item.title}</span>
        <span>· {resolvedLabel(item)}</span>
      </div>
    )
  }
  const plan = item.subject?.kind === 'plan' ? item.subject : undefined
  const deny = item.options.find((option) => option.id === 'deny')
  const [primary, ...others] = item.options.filter((option) => option.id !== 'deny')
  const isLink = item.detail?.startsWith('https://')
  return (
    <div className="space-y-2.5 rounded-lg border border-warning/50 bg-warning/5 p-3">
      <div className="flex items-center gap-2 font-medium">
        <Codicon name={plan ? 'checklist' : 'shield'} className="text-warning" />
        {item.title}
      </div>
      {item.description && <p className="text-xs text-muted-foreground">{item.description}</p>}
      {item.reason && <p className="text-xs text-warning">{item.reason}</p>}
      {plan && (
        <div className="space-y-1.5">
          <div className="max-h-80 overflow-auto rounded-md border bg-background/50 p-3 text-sm">
            <MessageResponse>{plan.text}</MessageResponse>
          </div>
          {plan.filePath && (
            <button
              type="button"
              className="text-xs text-muted-foreground hover:underline"
              onClick={() => send({ type: 'openFile', path: plan.filePath ?? '' })}
            >
              Plan file: <span className="font-mono">{plan.filePath}</span>
            </button>
          )}
        </div>
      )}
      {item.detail &&
        (isLink ? (
          <a href={item.detail} className="block truncate text-sm">
            {item.detail}
          </a>
        ) : (
          <pre className="max-h-40 overflow-auto rounded-md bg-code px-3 py-2 text-xs whitespace-pre-wrap">{item.detail}</pre>
        ))}
      <div className="flex flex-wrap items-center gap-2">
        {primary && (
          <Button size="sm" onClick={() => choose(item, primary.id)}>
            {primary.label}
            <Kbd>⏎</Kbd>
          </Button>
        )}
        {others.map((option) => (
          <Button key={option.id} size="sm" variant="secondary" onClick={() => choose(item, option.id)}>
            {option.label}
          </Button>
        ))}
        {item.diffIds && item.diffIds.length > 0 && (
          <Button size="sm" variant="ghost" onClick={() => send({ type: 'reviewChanges', itemIds: item.diffIds ?? [] })}>
            <Codicon name="diff" />
            Review changes
          </Button>
        )}
        <span className="flex-1" />
        {deny ? (
          <Button size="sm" variant="ghost" onClick={() => choose(item, deny.id)}>
            {deny.label}
            <Kbd>esc</Kbd>
          </Button>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => respond(item, { kind: 'dismiss' })}>
            Dismiss
            <Kbd>esc</Kbd>
          </Button>
        )}
      </div>
    </div>
  )
}

/** Enter takes the first option and Escape denies or dismisses the oldest pending approval, unless the user is typing. */
export function useApprovalKeys(items: SessionItem[]): void {
  const pending = items.find((item): item is ApprovalItem => item.kind === 'approval' && !item.resolved)
  useEffect(() => {
    if (!pending) return
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('textarea, input, [contenteditable="true"]')) return
      const primary = pending.options.find((option) => option.id !== 'deny')
      if (event.key === 'Enter' && primary) choose(pending, primary.id)
      else if (event.key === 'Escape') {
        if (pending.options.some((option) => option.id === 'deny')) choose(pending, 'deny')
        else respond(pending, { kind: 'dismiss' })
      } else return
      event.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pending])
}
```

- [ ] **Step 5: Wire up**

- In `webview/app/items/item-view.tsx`, import `QuestionCard` from `./question-card` and add `case 'question': return <QuestionCard item={item} />` before `case 'notice'`.
- In `webview/app/components/mode-picker.tsx`, add to `MODES` after `'accept-edits'`: `auto: { label: 'Auto', icon: 'sparkle' },`.

Run: `pnpm typecheck && pnpm test` → clean; PASS.

- [ ] **Step 6: Commit**

```bash
git add webview test/webview/question-state.test.ts
git commit -m "feat(webview): question cards, plan approvals, and richer approval cards"
```

---

### Task 8: Preview, live checks, hand-off

**Files:**
- Modify: `webview/preview/scenario.ts`, `esbuild.mjs`
- Create: `scripts/smoke-prompts.ts`

- [ ] **Step 1: A prompts scenario**

In `webview/preview/scenario.ts`, add before the `messages` selection:

```ts
const prompts: SessionItem[] = [
  { kind: 'message', id: 'pu1', role: 'user', parts: [{ type: 'text', text: 'Plan the retry fix.' }] },
  {
    kind: 'approval',
    id: 'approval:plan',
    title: 'Ready to code?',
    subject: {
      kind: 'plan',
      text: '1. Schedule the backoff with `await sleep(delay)`.\n2. Add a regression test with real timers.\n3. Run the suite 20 times.',
      filePath: '/work/.claude/plans/retry.md'
    },
    options: [
      { id: 'approve:ask', label: 'Approve · Ask before edits' },
      { id: 'approve:accept-edits', label: 'Approve · Accept edits' },
      { id: 'approve:auto', label: 'Approve · Auto' },
      { id: 'keep-planning', label: 'Keep planning' }
    ]
  },
  {
    kind: 'question',
    id: 'question:1',
    questions: [
      {
        id: 'q1',
        header: 'Backoff',
        question: 'Which backoff should the retry use?',
        multiSelect: false,
        allowOther: true,
        options: [
          { id: 'o1', label: 'Exponential', description: '100ms, 200ms, 400ms…' },
          { id: 'o2', label: 'Fixed', description: '250ms every time' }
        ]
      },
      { id: 'q2', question: 'Which suites should run?', multiSelect: true, allowOther: true, options: [{ id: 'o1', label: 'api' }, { id: 'o2', label: 'ui' }] }
    ]
  }
]
```

and make `?scenario=prompts` select `[providers, { type: 'provider', provider: claude }, { type: 'session', sessionId: 's1', event: { type: 'snapshot', record, status: 'needs-input', items: prompts, queue: [] } }]` (extend the existing `scenario` selection the same way `new` is selected).

- [ ] **Step 2: Screenshot review**

Run: `pnpm build:preview && pnpm screenshot dark 900x1100 panel prompts && pnpm screenshot dark 340x1100 view prompts`
Open both and check: the plan card shows "Ready to code?", the plan rendered as a numbered list, "Plan file: …", four buttons (the first primary with ⏎) and *Dismiss esc*; the question card shows "Question", the *Backoff* chip, "1 of 2", the question, two numbered options with descriptions, "Or type your answer", *Skip esc*, and a disabled *Next*. At 340 px nothing overflows (buttons wrap). Fix layout only in the two card files.

- [ ] **Step 3: Live checks**

`scripts/smoke-prompts.ts`:

```ts
// Live check: a provider asks a real question and gets an answer; Claude presents a real plan for approval.
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { SessionItem } from '../src/core/types'
import { captureEnv } from '../src/env'
import { providers } from '../src/providers/registry'
import { SessionManager } from '../src/sessions/manager'
import { SessionStore } from '../src/sessions/store'
import { MemoryMemento } from '../test/memory-memento'

const TIMEOUT_MS = 240_000

async function main(): Promise<void> {
  const providerId = process.argv[2] ?? 'claude'
  if (!providers.has(providerId)) throw new Error(`Unknown provider: ${providerId}`)
  const env = await captureEnv()
  const cwd = mkdtempSync(join(tmpdir(), 'agentdeck-prompts-'))
  writeFileSync(join(cwd, 'notes.md'), '# Notes\n\nhello world\n')
  const manager = new SessionManager({
    providers,
    store: new SessionStore(new MemoryMemento()),
    journalDir: join(cwd, '.journal'),
    cwd,
    env: async () => env
  })

  const ask = await manager.create(providerId)
  const asked = await turn(manager, ask.id, 'Before anything else, ask me which color I prefer using your tool for asking the user a question, with exactly two options: Red and Blue. After I answer, reply with just the color I chose.', (item) => {
    if (item.kind === 'question' && item.resolved === undefined) {
      const question = item.questions[0]
      const blue = question.options.find((option) => /blue/i.test(option.label))
      console.log('question:', question.question, question.options.map((option) => option.label))
      manager.answer(ask.id, item.id, { kind: 'answers', answers: [{ questionId: question.id, optionIds: blue ? [blue.id] : [], ...(blue ? {} : { other: 'Blue' }) }] })
      return true
    }
    return false
  })
  console.log(asked.prompted ? `${providerId} asked: PASS` : `${providerId} asked: NOT ASKED (answered in text)`)
  if (asked.prompted && !/blue/i.test(asked.reply)) throw new Error(`answer not received: ${JSON.stringify(asked.reply)}`)

  if (providerId === 'claude') {
    const plan = await manager.create('claude', 'plan')
    const planned = await turn(manager, plan.id, 'Plan how to replace "hello world" with "goodbye world" in notes.md. Present the plan for approval when ready.', (item) => {
      if (item.kind === 'approval' && item.subject?.kind === 'plan' && item.resolved === undefined) {
        console.log('plan:', item.subject.text.slice(0, 120).replaceAll('\n', ' '))
        manager.answer(plan.id, item.id, { kind: 'option', optionId: 'approve:accept-edits' })
        return true
      }
      if (item.kind === 'approval' && item.resolved === undefined) {
        manager.answer(plan.id, item.id, { kind: 'option', optionId: 'allow' })
      }
      return false
    })
    if (!planned.prompted) throw new Error('Claude did not present a plan for approval')
    const mode = manager.list().find(({ record }) => record.id === plan.id)?.record.mode
    console.log('mode after approval:', mode)
    if (mode !== 'accept-edits') throw new Error(`mode not switched: ${mode}`)
  }
  await manager.dispose()
  console.log('PROMPTS SMOKE OK')
}

/** Sends a prompt; `onItem` answers prompts and returns true when it handled the one being tested. */
function turn(
  manager: SessionManager,
  id: string,
  text: string,
  onItem: (item: SessionItem) => boolean
): Promise<{ prompted: boolean; reply: string }> {
  return new Promise((resolve, reject) => {
    let prompted = false
    const replies = new Map<string, string>()
    const timer = setTimeout(() => reject(new Error(`turn timed out: ${text}`)), TIMEOUT_MS)
    const subscription = manager.subscribe(id, (event) => {
      if (event.type !== 'item') return
      const item = event.item
      if (onItem(item)) prompted = true
      if (item.kind === 'message' && item.role === 'assistant') replies.set(item.id, item.text)
      if (item.kind === 'notice') console.log(`notice (${item.level}):`, item.text)
      if (item.kind === 'turn' && item.state === 'ended') {
        clearTimeout(timer)
        subscription.dispose()
        resolve({ prompted, reply: [...replies.values()].join('\n') })
      }
    })
    void manager.prompt(id, [{ type: 'text', text }])
  })
}

main().catch((error) => {
  console.error('PROMPTS SMOKE FAILED:', error)
  process.exit(1)
})
```

In `esbuild.mjs`, add `'smoke-prompts': 'scripts/smoke-prompts.ts'` to the extension build's `entryPoints`.

Run: `pnpm typecheck && pnpm build && node dist/smoke-prompts.js claude && node dist/smoke-prompts.js codex && node dist/smoke-prompts.js grok`
Expected: Claude `claude asked: PASS`, a `plan:` line, `mode after approval: accept-edits`, `PROMPTS SMOKE OK`. Codex and Grok each `… asked: PASS` or `… asked: NOT ASKED` (a model may answer in plain text instead of using its question tool; that is not a failure of AgentDeck), then `PROMPTS SMOKE OK`. A thrown error is a failure: report it in full. Then `node dist/smoke.js claude` → `SMOKE OK` (no regressions).

- [ ] **Step 4: Package and commit**

Run: `pnpm test && pnpm run package` → PASS; packaged.

```bash
git add webview/preview scripts/smoke-prompts.ts esbuild.mjs
git commit -m "test: preview prompts and check real questions and plan approval live"
```

- [ ] **Step 5: Hand off**

Ask the user to reinstall and check: ask Claude, Codex, and Grok each to "ask me a question with options before you start"; the question card appears (number keys pick, Skip dismisses and the agent waits); start a Claude chat in *Plan* mode and approve its plan with *Approve · Accept edits* (the mode picker changes); a Claude edit approval offers *Review changes*; *Allow for this session* on a command stops further asks for it in that chat.
