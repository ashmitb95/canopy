import { useEffect, useReducer } from 'react'
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

  if (state.empty) return <EmptyState providers={state.providers} />

  return (
    <TooltipProvider>
      <div className="flex h-screen flex-col">
        <ChatHeader state={state} />
        <Conversation className="min-h-0 flex-1">
          <ConversationContent className="gap-3 px-4 py-4">
            {state.items.map((item) => (
              <ItemView key={item.id} item={item} />
            ))}
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>
        <div className="space-y-2 px-3 pb-3">
          <SignInBanner provider={state.provider} />
          <WorkingStatus status={state.status} />
          <QueueList queue={state.queue} />
          <Composer state={state} />
        </div>
      </div>
    </TooltipProvider>
  )
}
