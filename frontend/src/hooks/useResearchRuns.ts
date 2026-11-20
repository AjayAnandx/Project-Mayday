import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../services/api'
import type { Claim, RunDetail, RunSummary, Source, TopicSummary } from '../types/research-run'

const POLL_MS = 3000

export function useResearchTopics() {
  const [topics, setTopics] = useState<TopicSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const list = await api.listResearch()
      setTopics((list as unknown as TopicSummary[]).slice().sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load research topics')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])
  return { topics, loading, error, refresh }
}

/** Runs of one topic + the selected run's detail; polls while that run is running. */
export function useResearchRuns(topic: string | null) {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [runId, setRunId] = useState<string | null>(null)
  const [run, setRun] = useState<RunDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  const loadRuns = useCallback(async () => {
    if (!topic) return
    try {
      const list = await api.listResearchRuns(topic)
      setRuns(list)
      setRunId(cur => (cur && list.some(r => r.id === cur) ? cur : list[0]?.id ?? null))
      setError(null)
    } catch (e) {
      setRuns([])
      setError(e instanceof Error ? e.message : 'Could not load runs')
    }
  }, [topic])

  useEffect(() => { setRuns([]); setRun(null); setRunId(null); loadRuns() }, [loadRuns])

  useEffect(() => {
    if (!topic || !runId) { setRun(null); return }
    let cancelled = false
    const tick = async () => {
      try {
        const detail = await api.getResearchRun(topic, runId)
        if (cancelled) return
        setRun(detail)
        if (detail.status === 'running') {
          timer.current = window.setTimeout(tick, POLL_MS)
        } else {
          loadRuns()  // refresh summaries once it finishes
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load run')
      }
    }
    tick()
    return () => { cancelled = true; if (timer.current) window.clearTimeout(timer.current) }
  }, [topic, runId, loadRuns])

  return { runs, run, runId, setRunId, error, reload: loadRuns }
}

export function useEvidence(topic: string | null, enabled: boolean, refreshKey: unknown) {
  const [claims, setClaims] = useState<Claim[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!topic || !enabled) return
    let cancelled = false
    setLoading(true)
    Promise.all([api.listResearchClaims(topic), api.listResearchSources(topic)])
      .then(([c, s]) => { if (!cancelled) { setClaims(c); setSources(s) } })
      .catch(() => { if (!cancelled) { setClaims([]); setSources([]) } })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [topic, enabled, refreshKey])

  return { claims, sources, loading }
}
