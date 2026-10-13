import { useState, useEffect, useCallback } from 'react'
import type { GmailStatus } from '../types/gmail'
import { api } from '../services/api'

interface UseGmailReturn {
  status: GmailStatus | null
  unreadCount: number
  loading: boolean
  needsReconnect: string | null
  refresh: () => void
  connect: () => void
}

export function useGmail(pollMs = 30000): UseGmailReturn {
  const [status, setStatus] = useState<GmailStatus | null>(null)
  const [unreadCount, setUnreadCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [needsReconnect, setNeedsReconnect] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const refresh = useCallback(() => setRefreshKey(k => k + 1), [])
  const connect = useCallback(() => api.startGmailAuth('agent'), [])

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
              const msg = e instanceof Error ? e.message : ''
              if (/40[13]|scope|connect|unauthorized|forbidden/i.test(msg)) {
                try {
                  const detail = JSON.parse(msg)
                  setNeedsReconnect(typeof detail.detail === 'string' ? detail.detail : msg)
                } catch {
                  setNeedsReconnect(msg || 'Gmail needs reconnecting')
                }
              }
            }
          }
        } else if (!cancelled) {
          setUnreadCount(0)
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

  return { status, unreadCount, loading, needsReconnect, refresh, connect }
}
