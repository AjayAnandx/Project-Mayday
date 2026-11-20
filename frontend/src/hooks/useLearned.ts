import { useCallback, useEffect, useState } from 'react'

export interface LearnedItem {
  kind: 'fact' | 'commitment' | 'idea' | 'lesson'
  scope?: string
  votes?: number
  uses?: number
  id: string
  status: string
  text: string
  quote: string
  source_ref?: string
  created_at: string
  confidence?: number
  subject?: string
  predicate?: string
  object?: string
  sensitivity?: string
  supersedes?: string | null
  due?: string | null
  planner_item_id?: string | null
}

export type LearnedFilter = 'all' | 'pending' | 'active'

export function useLearned() {
  const [items, setItems] = useState<LearnedItem[]>([])
  const [counts, setCounts] = useState<{ active: number; pending: number }>({ active: 0, pending: 0 })
  const [filter, setFilter] = useState<LearnedFilter>('all')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const q = filter === 'all' ? '' : `?status=${filter}`
      const res = await fetch(`/api/brain/learned${q}`)
      if (!res.ok) throw new Error(res.status === 409 ? 'Capture needs the SQLite brain (memory.backend: sqlite).' : `HTTP ${res.status}`)
      const data = await res.json()
      setItems(data.items ?? [])
      setCounts(data.counts ?? { active: 0, pending: 0 })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { load() }, [load])

  const act = useCallback(async (item: LearnedItem, action: 'confirm' | 'reject') => {
    const res = await fetch(`/api/brain/learned/${item.kind}/${item.id}/${action}`, { method: 'POST' })
    if (res.ok) await load()
    return res.ok
  }, [load])

  const edit = useCallback(async (item: LearnedItem, value: string) => {
    const res = await fetch(`/api/brain/learned/fact/${item.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ object: value }),
    })
    if (res.ok) await load()
    return res.ok
  }, [load])

  return { items, counts, filter, setFilter, loading, error, reload: load, act, edit }
}
