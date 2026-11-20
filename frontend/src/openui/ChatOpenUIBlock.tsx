import { lazy, Suspense } from 'react'
import { useChatContext } from '../context/ChatContext'
import type { UiPayload } from '../types/chat'

// OpenUI + Zod load only when a card is first shown, keeping them out of the main bundle.
const OpenUIBlock = lazy(() => import('./OpenUIBlock').then(m => ({ default: m.OpenUIBlock })))

/** OpenUIBlock wired to the chat: buttons send messages or approve paused phases. */
export function ChatOpenUIBlock({ ui, expandable = true }: { ui: UiPayload; expandable?: boolean }) {
  const { sendMessage, confirmPhase } = useChatContext()
  return (
    <Suspense fallback={<p className="text-xs text-overlay1">Loading…</p>}>
      <OpenUIBlock ui={ui} onSend={sendMessage} onConfirmPhase={confirmPhase} expandable={expandable} />
    </Suspense>
  )
}
