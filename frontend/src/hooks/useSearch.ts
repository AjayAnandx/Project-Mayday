import { useState, useEffect, useRef } from 'react'
import type { SearchResults } from '../types/search'
import { api } from '../services/api'

export function useSearch(query: string) {
  const [results, setResults] = useState<SearchResults | null>(null)
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController>()

  useEffect(() => {
    if (!query.trim()) {
      setResults(null)
      setLoading(false)
      return
    }

    if (abortRef.current) abortRef.current.abort()
    abortRef.current = new AbortController()
    setLoading(true)

    const timer = setTimeout(async () => {
      try {
        const data = await api.searchAll(query)
        setResults(data)
      } catch {
        if (!abortRef.current?.signal.aborted) setResults(null)
      } finally {
        if (!abortRef.current?.signal.aborted) setLoading(false)
      }
    }, 300)

    return () => {
      clearTimeout(timer)
      abortRef.current?.abort()
    }
  }, [query])

  return { results, loading }
}
