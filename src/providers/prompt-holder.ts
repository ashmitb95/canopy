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
