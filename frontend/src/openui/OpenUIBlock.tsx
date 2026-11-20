import { Renderer } from '@openuidev/react-lang'
import { Maximize2 } from 'lucide-react'
import { library, safeUrl } from './library'
import type { UiPayload } from '../types/chat'

interface Props {
  ui: UiPayload
  onSend?: (text: string) => void
  onConfirmPhase?: (phase: string) => void
  expandable?: boolean
}

/** Renders a backend-built OpenUI spec and routes its actions into Mayday's existing paths. */
export function OpenUIBlock({ ui, onSend, onConfirmPhase, expandable = true }: Props) {
  const onAction = (event: { type: string; params: Record<string, unknown>; humanFriendlyMessage: string }) => {
    const p = event.params ?? {}
    if (event.type === 'open_url') {
      const url = safeUrl(String(p.url ?? ''))
      if (url) window.open(url, '_blank', 'noopener')
    } else if (event.type === 'continue_conversation') {
      onSend?.(event.humanFriendlyMessage)
    } else if (event.type === 'approve_phase') {
      onConfirmPhase?.(String(p.phase ?? 'any'))
    } else if (event.type === 'reject_phase') {
      onSend?.(`Stop: do not continue phase ${String(p.phase ?? '')}.`)
    }
  }
  // Popping out only helps for larger content; small cards (a download link) stay inline.
  const canExpand = expandable && /\b(Chart|Table|Card)\(/.test(ui.lang)
  return (
    <div className="relative">
      {canExpand && (
        <button type="button" title="Open in side panel" aria-label="Open in side panel"
                onClick={() => window.dispatchEvent(new CustomEvent('open-artifact', { detail: { ui, title: ui.title } }))}
                className="absolute right-2 top-2 z-10 rounded-lg p-1.5 text-overlay1 hover:bg-white/[0.06] hover:text-text">
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
      )}
      <Renderer response={ui.lang} library={library} onAction={onAction as never} />
    </div>
  )
}
