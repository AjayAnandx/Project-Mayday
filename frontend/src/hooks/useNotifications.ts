import { useEffect, useRef } from 'react'

interface NotificationMessage {
  type: 'notification'
  id: string
  title: string
  body: string
  category: string
  action?: { page: string }
}

export type Toast = { id: string; title: string; body: string }
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
  setTimeout(() => {
    toastSubscribers.forEach(fn =>
      fn({ id: toast.id + '_dismiss', title: '', body: '' })
    )
  }, 5000)
}

export function useNotifications() {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    const poll = async () => {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const url = `${protocol}//${location.host}/api/notifications/fired`

      // Use fetch via the REST endpoint
      const httpUrl = url.replace(/^ws:/, 'http:').replace(/^wss:/, 'https:')
      try {
        const res = await fetch(httpUrl)
        if (!res.ok) return
        const data: NotificationMessage[] = await res.json()
        for (const item of data) {
          if (item.type !== 'notification') continue

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
            emitToast({ id: item.id, title: item.title, body: item.body })
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
