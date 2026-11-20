import { useEffect, useRef } from 'react'

interface NotificationMessage {
  type: 'notification'
  id: string
  title: string
  body: string
  category: string
  speak?: string
  action?: { page: string }
  /** planner alerts: the item to act on + which actions to offer */
  item_id?: string
  item_kind?: string
  actions?: ('done' | 'snooze')[]
  /** Brain V3 proactive suggestions */
  suggestion_id?: string
  why?: string
  mode?: 'nudge' | 'framing' | 'autonomous'
  options?: string[]
  action_id?: string | null
  has_action?: boolean
  chat_prompt?: string | null
}

export type Toast = {
  id: string; title: string; body: string; item_id?: string; actions?: ('done' | 'snooze')[]
  suggestion_id?: string; why?: string; mode?: 'nudge' | 'framing' | 'autonomous'; options?: string[]
  action_id?: string | null; has_action?: boolean; chat_prompt?: string | null
}
type ToastHandler = (toast: Toast) => void

let toastSubscribers: ToastHandler[] = []

export function subscribeToasts(fn: ToastHandler) {
  toastSubscribers.push(fn)
  return () => {
    toastSubscribers = toastSubscribers.filter(f => f !== fn)
  }
}

function emitToast(toast: Toast) {
  toastSubscribers.forEach(fn => fn(toast))
  if (toast.item_id || toast.suggestion_id) return // actionable toasts stay until handled
  setTimeout(() => {
    toastSubscribers.forEach(fn =>
      fn({ id: toast.id + '_dismiss', title: '', body: '' })
    )
  }, 5000)
}

export function useNotifications() {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // broadcast cursor: every open tab/device receives every notification
  const seqRef = useRef(-1)

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch(`/api/notifications/fired?since=${seqRef.current}`)
        if (!res.ok) return
        const { seq, items: data } = await res.json() as { seq: number; items: NotificationMessage[] }
        seqRef.current = seq
        for (const item of data) {
          if (item.type !== 'notification') continue
          // Finished research carries spoken text; classic voice mode (if open) reads it aloud.
          if (item.speak) {
            window.dispatchEvent(new CustomEvent('mayday-speak', { detail: { text: item.speak } }))
          }

          // Browser notification (best-effort)
          if (Notification.permission === 'granted') {
            try {
              const notif = new Notification(item.title, {
                body: item.body,
                tag: item.id,
                icon: '/favicon.ico',
              })
              notif.onclick = () => {
                window.focus()
                if (item.action?.page) {
                  window.dispatchEvent(
                    new CustomEvent('navigate', { detail: item.action.page })
                  )
                }
                notif.close()
              }
            } catch {
              // browser notification failed, fallback to in-app
            }
          }

          // In-app toast (works without permission)
          if (item.category !== 'custom_reminder') {
            emitToast({ id: item.id, title: item.title, body: item.body, item_id: item.item_id, actions: item.actions,
              suggestion_id: item.suggestion_id, why: item.why, mode: item.mode, options: item.options,
              action_id: item.action_id, has_action: item.has_action, chat_prompt: item.chat_prompt })
            if (item.item_id) window.dispatchEvent(new CustomEvent('planner-changed'))
          }

          // Dispatch reminder modal event
          if (item.category === 'custom_reminder') {
            window.dispatchEvent(
              new CustomEvent('reminder-fired', {
                detail: {
                  id: item.id,
                  title: item.title,
                  body: item.body,
                  category: item.category,
                  item_id: item.item_id,
                  actions: item.actions,
                },
              })
            )
          }
        }
      } catch {
        // poll error — will retry on next interval
      }
    }

    // Request notification permission on first user interaction
    const grantOnInteraction = () => {
      if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission()
      }
      window.removeEventListener('click', grantOnInteraction)
    }
    window.addEventListener('click', grantOnInteraction)

    // Poll every 3 seconds
    poll()
    intervalRef.current = setInterval(poll, 3000)

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
      window.removeEventListener('click', grantOnInteraction)
    }
  }, [])
}
