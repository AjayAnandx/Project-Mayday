// Brain V3 P8: behavioural signals from the web UI (laptop or phone).
// Only numbers and categories are sent: never message text, titles or URLs.
// Every call is fire-and-forget and silently ignores errors.

type Kind = 'response_latency' | 'ui_visibility' | 'ui_dismiss' | 'ui_edit' | 'suggestion_feedback'

const device = (): 'phone' | 'tablet' | 'desktop' => {
  try {
    if (window.matchMedia('(pointer: coarse)').matches) {
      return window.innerWidth < 768 ? 'phone' : 'tablet'
    }
  } catch { /* older browsers */ }
  return 'desktop'
}

export function sendSignal(kind: Kind, value: Record<string, number | string | boolean | null> = {}, subject?: string) {
  try {
    const body = JSON.stringify({ kind, value: { device: device(), ...value }, subject })
    if (navigator.sendBeacon && kind === 'ui_visibility') {
      navigator.sendBeacon('/api/brain/signals', new Blob([body], { type: 'application/json' }))
      return
    }
    void fetch('/api/brain/signals', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true })
      .catch(() => undefined)
  } catch { /* never break the UI */ }
}

// ---- response latency: assistant finished -> user's next message, minus time the tab was hidden
let assistantDoneAt: number | null = null
let hiddenSince: number | null = typeof document !== 'undefined' && document.hidden ? Date.now() : null
let hiddenMs = 0

export function markAssistantDone() {
  assistantDoneAt = Date.now()
  hiddenMs = 0
  hiddenSince = document.hidden ? Date.now() : null
}

export function markUserSend(chars: number) {
  if (assistantDoneAt == null) return
  const now = Date.now()
  const hidden = hiddenMs + (hiddenSince != null ? now - hiddenSince : 0)
  const latency = Math.max(0, now - assistantDoneAt - hidden)
  assistantDoneAt = null
  if (latency > 6 * 3600 * 1000) return          // a new session, not a reply
  sendSignal('response_latency', { ms: latency, hidden_ms: hidden, chars })
}

let visibilityWired = false
export function wireVisibility() {
  if (visibilityWired || typeof document === 'undefined') return
  visibilityWired = true
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      hiddenSince = Date.now()
    } else if (hiddenSince != null) {
      hiddenMs += Date.now() - hiddenSince
      hiddenSince = null
    }
    sendSignal('ui_visibility', { visible: !document.hidden })
  })
}
