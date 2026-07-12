import { useState, useEffect, useCallback } from 'react'
import type { DashboardData, AiNewsResponse, DashboardWeather } from '../types/dashboard'
import { api } from '../services/api'

interface UseDashboardReturn {
  data: DashboardData | null
  weather: DashboardWeather | null
  aiNews: AiNewsResponse | null
  loading: boolean
  error: string | null
  refresh: () => void
}

export function useDashboard(toolCallCount: number): UseDashboardReturn {
  const [data, setData] = useState<DashboardData | null>(null)
  const [weather, setWeather] = useState<DashboardWeather | null>(null)
  const [aiNews, setAiNews] = useState<AiNewsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const refresh = useCallback(() => setRefreshKey(k => k + 1), [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    Promise.all([
      api.getDashboard(),
      api.getDashboardWeather().catch(() => null),
      api.getAiNews().catch(() => null),
    ]).then(([d, w, n]) => {
      if (cancelled) return
      setData(d)
      setWeather(w)
      setAiNews(n)
      setLoading(false)
    }).catch((err) => {
      if (cancelled) return
      setError(err instanceof Error ? err.message : 'Failed to load dashboard')
      setLoading(false)
    })

    return () => { cancelled = true }
  }, [refreshKey, toolCallCount])

  return { data, weather, aiNews, loading, error, refresh }
}
