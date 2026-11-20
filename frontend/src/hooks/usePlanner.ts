import { useCallback, useEffect, useState } from 'react'
import { api } from '../services/api'
import { useChatContext } from '../context/ChatContext'
import { notifyPlannerChanged } from '../lib/planner'
import type { Person, PlannerItem, PlannerItemInput, PlannerSummary, PlannerView } from '../types/planner'

export interface PlannerFilter {
  view: PlannerView
  list?: string
  tag?: string
  q?: string
  person_id?: string
}

/** Reload trigger shared by every planner surface: chat tool calls + local edits. */
export function usePlannerVersion() {
  const { toolCallCount } = useChatContext()
  const [local, setLocal] = useState(0)
  useEffect(() => {
    const bump = () => setLocal(v => v + 1)
    window.addEventListener('planner-changed', bump)
    return () => window.removeEventListener('planner-changed', bump)
  }, [])
  return toolCallCount * 10_000 + local
}

export function usePlanner(filter: PlannerFilter) {
  const version = usePlannerVersion()
  const [items, setItems] = useState<PlannerItem[]>([])
  const [summary, setSummary] = useState<PlannerSummary | null>(null)
  const [people, setPeople] = useState<Person[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { view, list, tag, q, person_id } = filter

  useEffect(() => {
    if (view === 'calendar') return // calendar loads its own range
    let cancelled = false
    setLoading(true)
    api.planner.list({ view, list, tag, q, person_id, days: view === 'upcoming' ? 14 : undefined })
      .then(r => { if (!cancelled) { setItems(r); setError(null) } })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [view, list, tag, q, person_id, version])

  useEffect(() => {
    let cancelled = false
    Promise.all([api.planner.summary(), api.planner.people()])
      .then(([s, p]) => { if (!cancelled) { setSummary(s); setPeople(p) } })
      .catch(() => {})
    return () => { cancelled = true }
  }, [version])

  return { items, summary, people, loading, error }
}

/** Mutations — each one broadcasts planner-changed so all views refresh. */
export function usePlannerActions() {
  const wrap = useCallback(<A extends unknown[], R>(fn: (...a: A) => Promise<R>) =>
    async (...a: A): Promise<R> => {
      const r = await fn(...a)
      notifyPlannerChanged()
      return r
    }, [])

  return {
    create: wrap((data: PlannerItemInput) => api.planner.create(data)),
    update: wrap((id: string, data: PlannerItemInput) => api.planner.update(id, data)),
    remove: wrap((id: string) => api.planner.remove(id)),
    complete: wrap((id: string, done?: boolean) => api.planner.complete(id, done ?? true)),
    snooze: wrap((id: string, opts: { minutes?: number; until?: string }) => api.planner.snooze(id, opts)),
    schedule: wrap((id: string, start: string | null, end?: string | null) => api.planner.schedule(id, start, end)),
    quickAdd: wrap((text: string) => api.planner.quickAdd(text, true)),
    delegate: wrap((d: Parameters<typeof api.planner.delegate>[0]) => api.planner.delegate(d)),
    nudge: wrap((id: string) => api.planner.nudge(id)),
    createPerson: wrap((d: Parameters<typeof api.planner.createPerson>[0]) => api.planner.createPerson(d)),
    updatePerson: wrap((id: string, d: Partial<Person>) => api.planner.updatePerson(id, d)),
    deletePerson: wrap((id: string) => api.planner.deletePerson(id)),
  }
}
