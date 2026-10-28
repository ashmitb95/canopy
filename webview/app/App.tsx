import { Fragment, useEffect, useMemo, useReducer, useState } from 'react'
import { Conversation, ConversationContent, ConversationScrollButton } from '@/components/ai-elements/conversation'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ChatHeader } from './components/chat-header'
import { Composer } from './components/composer'
import { EmptyState } from './components/empty-state'
import { SignInBanner } from './components/sign-in-banner'
import { QueueList } from './components/queue-list'
import { WorkingStatus } from './components/working-status'
import { onHostMessage, saveState, send } from './host'
import { useApprovalKeys } from './items/approval-card'
import { ItemView } from './items/item-view'
import { selectedModel } from './components/model-picker'
import { TurnFooterView } from './items/turn-footer'
import { turnFooters } from './turns'
import { initialState, reduce } from './state'

export function App() {
  const [state, dispatch] = useReducer(reduce, initialState)

  useEffect(() => {
    const unsubscribe = onHostMessage(dispatch)
    send({ type: 'ready' })
    return unsubscribe
  }, [])

  useEffect(() => {
    if (state.sessionId) saveState({ sessionId: state.sessionId })
  }, [state.sessionId])

  useApprovalKeys(state.items)

  const footers = useMemo(() => turnFooters(state.items), [state.items])
  const modelFact = state.facts.model?.kind === 'model' ? state.facts.model : undefined
  const model = modelFact ? (selectedModel(modelFact)?.label ?? modelFact.current) : undefined
  const busy = state.status === 'running' || state.status === 'needs-input'
  const [since, setSince] = useState<number>()
  useEffect(() => setSince((started) => (busy ? (started ?? Date.now()) : undefined)), [busy])

  if (state.empty) return <EmptyState providers={state.providers} />

  return (
    <TooltipProvider>
      <div className="flex h-screen flex-col">
        <ChatHeader state={state} />
        <Conversation className="min-h-0 flex-1">
          <ConversationContent className="gap-3 px-4 py-4">
            {state.items.map((item) => {
              const footer = footers.get(item.id)
              return (
                <Fragment key={item.id}>
                  <ItemView item={item} />
                  {footer && <TurnFooterView footer={footer} model={model} />}
                </Fragment>
              )
            })}
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>
        <div className="space-y-2 px-3 pb-3">
          <SignInBanner provider={state.provider} />
          <WorkingStatus status={state.status} since={since} />
          <QueueList queue={state.queue} />
          <Composer state={state} />
        </div>
      </div>
    </TooltipProvider>
  )
}
