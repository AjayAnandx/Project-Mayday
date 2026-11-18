import { useState, useEffect, useCallback } from 'react'
import type { GmailStatus } from '../types/gmail'
import { api } from '../services/api'

interface UseGmailReturn {
  status: GmailStatus | null
  unreadCount: number
  loading: boolean
  needsReconnect: string | null
  userUnread: number
  userNeedsReconnect: string | null
  userWatching: boolean
  refresh: () => void
  connect: () => void
  connectUser: () => void
}

function reconnectMessage(e: unknown): string | null {
  const msg = e instanceof Error ? e.message : ''
  if (!/40[13]|scope|connect|unauthorized|forbidden/i.test(msg)) return null
  try {
    const detail = JSON.parse(msg)
    return typeof detail.detail === 'string' ? detail.detail : msg
  } catch {
    return msg || 'Gmail needs reconnecting'
  }
}

export function useGmail(pollMs = 30000): UseGmailReturn {
  const [status, setStatus] = useState<GmailStatus | null>(null)
  const [unreadCount, setUnreadCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [needsReconnect, setNeedsReconnect] = useState<string | null>(null)
  const [userUnread, setUserUnread] = useState(0)
  const [userNeedsReconnect, setUserNeedsReconnect] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const refresh = useCallback(() => setRefreshKey(k => k + 1), [])
  const connect = useCallback(() => api.startGmailAuth('agent'), [])
  const connectUser = useCallback(() => api.startGmailAuth('user'), [])

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setInterval> | undefined

    const fetchOnce = async () => {
      try {
        const s = await api.getGmailStatus()
        if (cancelled) return
        setStatus(s)
        setLoading(false)
        if (s.authenticated) {
          try {
            const m = await api.listGmailMessages('is:unread', 1)
            if (!cancelled) {
              setUnreadCount(m.resultSizeEstimate ?? m.messages.length)
              setNeedsReconnect(null)
            }
          } catch (e) {
            // 401/403 = token missing scope or expired -> offer reconnect
            // instead of silently showing a dead "connected" badge.
            if (!cancelled) {
              const r = reconnectMessage(e)
              if (r) setNeedsReconnect(r)
            }
          }
        } else if (!cancelled) {
          setUnreadCount(0)
        }
        // Personal slot (read-only watch) — only when enabled server-side.
        const watching = s.account === 'both' || s.account === 'user'
        if (watching && s.user?.authenticated) {
          try {
            const m = await api.listGmailMessages('is:unread', 1, 'user')
            if (!cancelled) {
              setUserUnread(m.resultSizeEstimate ?? m.messages.length)
              setUserNeedsReconnect(null)
            }
          } catch (e) {
            if (!cancelled) {
              const r = reconnectMessage(e)
              if (r) setUserNeedsReconnect(r)
            }
          }
        } else if (!cancelled) {
          setUserUnread(0)
          if (!watching) setUserNeedsReconnect(null)
        }
      } catch {
        if (!cancelled) setLoading(false)
      }
    }

    fetchOnce()
    if (pollMs > 0) timer = setInterval(fetchOnce, pollMs)
    // Re-check right after the OAuth tab closes (user returns to Mayday)
    const onFocus = () => fetchOnce()
    window.addEventListener('focus', onFocus)
    return () => {
      cancelled = true
      if (timer) clearInterval(timer)
      window.removeEventListener('focus', onFocus)
    }
  }, [pollMs, refreshKey])

  return { status, unreadCount, loading, needsReconnect, userUnread, userNeedsReconnect,
           userWatching: status?.account === 'both' || status?.account === 'user',
           refresh, connect, connectUser }
}
