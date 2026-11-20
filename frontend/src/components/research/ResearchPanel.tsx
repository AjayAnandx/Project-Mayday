import { useEffect, useState } from 'react'
import { BookMarked, Check, FileCode2, FileSpreadsheet, FileText, FlaskConical, Loader2, Plus, Search } from 'lucide-react'
import { cn } from '../../lib/utils'
import { api } from '../../services/api'
import { useEvidence, useResearchRuns, useResearchTopics } from '../../hooks/useResearchRuns'
import { AnswersView, EvidenceView, HypothesesView, RunLogView, SourcesView, StageProgress } from './ResearchViews'
import type { Preset, RunSummary } from '../../types/research-run'

type Tab = 'answers' | 'hypotheses' | 'evidence' | 'sources' | 'log'
const TABS: { id: Tab; label: string }[] = [
  { id: 'answers', label: 'Answers' },
  { id: 'hypotheses', label: 'Hypotheses' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'sources', label: 'Sources' },
  { id: 'log', label: 'Run log' },
]
const FIELDS: { id: string; label: string }[] = [
  { id: 'general', label: 'General science' },
  { id: 'cs_ml', label: 'CS / ML / engineering' },
  { id: 'social_science', label: 'Social science / economics' },
]
const TYPES = ['domain', 'market', 'technical', 'financial', 'academic', 'competitive', 'product', 'legal',
  'person_org', 'trend', 'business', 'sales', 'community']
const PRESETS: { id: Preset; label: string; hint: string }[] = [
  { id: 'quick', label: 'Quick', hint: '≈3 min · 15 sources · $0.10' },
  { id: 'standard', label: 'Standard', hint: '≈10 min · 40 sources · $0.50' },
  { id: 'deep', label: 'Deep', hint: '≈30 min · 120 sources · $2' },
]

function statusTone(s: string) {
  return s === 'completed' ? 'text-green' : s === 'running' ? 'text-text' : s === 'failed' ? 'text-red' : 'text-yellow'
}

function NewRunForm({ initialTopic, onStarted, onCancel }: {
  initialTopic: string; onStarted: (topic: string) => void; onCancel: () => void
}) {
  const [topic, setTopic] = useState(initialTopic)
  const [request, setRequest] = useState('')
  const [type, setType] = useState('domain')
  const [preset, setPreset] = useState<Preset>('standard')
  const [field, setField] = useState('general')
  const [snowball, setSnowball] = useState(true)
  const [hypotheses, setHypotheses] = useState('')
  const [adapters, setAdapters] = useState<{ name: string; description: string }[]>([])
  const [sources, setSources] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const academic = type === 'academic'

  useEffect(() => {
    api.listResearchAdapters().then(setAdapters).catch(() => setAdapters([]))
  }, [])
  const toggleSource = (n: string) => setSources(s => (s.includes(n) ? s.filter(x => x !== n) : [...s, n]))

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!topic.trim()) return
    setBusy(true)
    setError(null)
    try {
      const hyps = hypotheses.split('\n').map(h => h.trim()).filter(Boolean)
      await api.startResearchRun({
        topic: topic.trim(), request: request.trim() || topic.trim(), type, preset,
        ...(academic ? { field, snowball, ...(hyps.length ? { hypotheses: hyps } : {}) } : {}),
        ...(sources.length ? { sources } : {}),
      })
      onStarted(topic.trim())
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Could not start the run'
      try { setError(JSON.parse(msg).detail ?? msg) } catch { setError(msg) }
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="rounded-[20px] border border-white/[0.06] bg-base p-4 space-y-3">
      <h2 className="text-sm font-medium">New research run</h2>
      <input value={topic} onChange={e => setTopic(e.target.value)} placeholder="Topic, e.g. India EV battery costs 2026"
             className="w-full rounded-xl bg-surface0 px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-green/60" />
      <textarea value={request} onChange={e => setRequest(e.target.value)} rows={3}
                placeholder="What do you want to know? (questions, scope, region, time frame)"
                className="w-full rounded-xl bg-surface0 px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-green/60 resize-none" />
      <div className="flex flex-wrap items-center gap-2">
        <select value={type} onChange={e => setType(e.target.value)} aria-label="Research category"
                className="rounded-xl bg-surface0 px-3 py-2 text-sm outline-none">
          {TYPES.map(t => <option key={t} value={t}>{t.replace('_', ' / ')}</option>)}
        </select>
        <div className="flex gap-1" role="radiogroup" aria-label="Budget">
          {PRESETS.map(p => (
            <button type="button" key={p.id} role="radio" aria-checked={preset === p.id} title={p.hint}
                    onClick={() => setPreset(p.id)}
                    className={cn('rounded-xl px-3 py-2 text-xs', preset === p.id ? 'bg-white/[0.1] text-text' : 'text-subtext0 hover:bg-white/[0.04]')}>
              {p.label}
            </button>
          ))}
        </div>
        <span className="text-[11px] text-overlay1">{PRESETS.find(p => p.id === preset)?.hint}</span>
      </div>
      {academic && (
        <div className="space-y-2 rounded-xl border border-white/[0.06] p-3">
          <div className="flex flex-wrap items-center gap-3">
            <select value={field} onChange={e => setField(e.target.value)} aria-label="Discipline"
                    className="rounded-xl bg-surface0 px-3 py-2 text-sm outline-none">
              {FIELDS.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
            </select>
            <label className="flex items-center gap-2 text-xs text-subtext0">
              <input type="checkbox" checked={snowball} onChange={e => setSnowball(e.target.checked)} className="accent-green" />
              Follow citations (references and citing papers)
            </label>
          </div>
          <textarea value={hypotheses} onChange={e => setHypotheses(e.target.value)} rows={2}
                    placeholder="Hypotheses to test, one per line (optional; Mayday proposes some if empty)"
                    className="w-full rounded-xl bg-surface0 px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-green/60 resize-none" />
        </div>
      )}
      {adapters.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5" aria-label="Sources">
          <span className="text-[11px] text-overlay1 mr-1">Sources:</span>
          {adapters.map(a => (
            <button type="button" key={a.name} title={a.description} onClick={() => toggleSource(a.name)}
                    aria-pressed={sources.includes(a.name)}
                    className={cn('rounded-full px-2.5 py-1 text-[11px]',
                      sources.includes(a.name) ? 'bg-green/15 text-green' : 'bg-white/[0.04] text-subtext0 hover:bg-white/[0.08]')}>
              {a.name}
            </button>
          ))}
          <span className="text-[11px] text-overlay1">{sources.length ? 'only these' : 'all (pick to restrict)'}</span>
        </div>
      )}
      {error && <p className="text-xs text-red">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || !topic.trim()}
                className="flex items-center gap-1.5 rounded-full bg-green px-4 py-2 text-xs font-medium text-crust disabled:opacity-50">
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="h-3.5 w-3.5" />} Start research
        </button>
        <button type="button" onClick={onCancel} className="rounded-full px-4 py-2 text-xs text-subtext0 hover:bg-white/[0.04]">Cancel</button>
      </div>
    </form>
  )
}

function RunPicker({ runs, runId, onPick }: { runs: RunSummary[]; runId: string | null; onPick: (id: string) => void }) {
  if (runs.length < 2) return null
  return (
    <select value={runId ?? ''} onChange={e => onPick(e.target.value)} aria-label="Run"
            className="rounded-xl bg-surface0 px-2 py-1.5 text-xs outline-none">
      {runs.map(r => (
        <option key={r.id} value={r.id}>
          {new Date(r.started_at).toLocaleString()} · {r.status} · {r.answered}/{r.questions.length} answered
        </option>
      ))}
    </select>
  )
}

export function ResearchPanel() {
  const { topics, loading, error, refresh } = useResearchTopics()
  const [filter, setFilter] = useState('')
  const [topic, setTopic] = useState<string | null>(null)
  const [creating, setCreating] = useState<string | null>(null)  // null = closed; '' = new topic
  const [tab, setTab] = useState<Tab>('answers')
  const [exporting, setExporting] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const { runs, run, runId, setRunId, error: runError, reload } = useResearchRuns(topic)
  const evidence = useEvidence(topic, tab === 'evidence' || tab === 'sources', `${runId}:${run?.status}:${run?.stages.length}`)

  useEffect(() => { if (!topic && topics.length) setTopic(topics[0].topic) }, [topics, topic])

  const shown = topics.filter(t => t.topic.toLowerCase().includes(filter.toLowerCase()))
  const copyBibtex = async () => {
    if (!topic) return
    try {
      const { text } = await api.getResearchCite(topic, 'bibtex')
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Could not copy citations')
    }
  }
  const doExport = async (format: 'docx' | 'xlsx' | 'md' | 'bib' | 'tex') => {
    if (!topic || !run) return
    setExporting(format)
    try {
      const res = format === 'md' ? await api.getResearchRunReport(topic, run.id) : await api.exportResearchRun(topic, run.id, format)
      window.open(res.url, '_blank', 'noopener')
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Export failed')
    } finally {
      setExporting(null)
    }
  }

  return (
    <div className="h-full overflow-hidden bg-crust">
      <div className="h-full max-w-[1400px] mx-auto px-3 sm:px-6 pt-5 pb-4 flex flex-col lg:flex-row gap-4">
        <aside className="lg:w-72 shrink-0 flex flex-col gap-2 min-h-0 max-h-56 lg:max-h-none">
          <button onClick={() => setCreating('')}
                  className="flex items-center justify-center gap-1.5 rounded-full bg-green px-4 py-2 text-xs font-medium text-crust">
            <Plus className="h-3.5 w-3.5" /> New research
          </button>
          <label className="flex items-center gap-2 rounded-xl bg-surface0 px-3 py-1.5">
            <Search className="h-3.5 w-3.5 text-overlay1" />
            <input value={filter} onChange={e => setFilter(e.target.value)} placeholder="Filter topics"
                   className="flex-1 bg-transparent text-sm outline-none" />
          </label>
          <nav aria-label="Research topics" className="flex-1 min-h-0 overflow-y-auto space-y-0.5">
            {loading && <p className="px-3 text-xs text-overlay1">Loading…</p>}
            {error && <p className="px-3 text-xs text-red">{error}</p>}
            {!loading && !shown.length && <p className="px-3 text-xs text-overlay1">No research yet.</p>}
            {shown.map(t => (
              <button key={t.id} onClick={() => { setTopic(t.topic); setCreating(null); setTab('answers') }}
                      aria-current={t.topic === topic ? 'page' : undefined}
                      className={cn('w-full text-left rounded-xl px-3 py-2 transition-colors',
                        t.topic === topic ? 'bg-white/[0.08]' : 'hover:bg-white/[0.04]')}>
                <span className="block truncate text-sm text-text">{t.topic}</span>
                <span className="text-[11px] text-overlay1">{t.type.replace('_', ' / ')} · {t.status}</span>
              </button>
            ))}
          </nav>
        </aside>

        <main className="flex-1 min-w-0 min-h-0 overflow-y-auto space-y-4 pb-6">
          {creating !== null && (
            <NewRunForm key={creating} initialTopic={creating} onCancel={() => setCreating(null)}
                        onStarted={t => { setCreating(null); refresh(); setTopic(t); setTab('answers'); setTimeout(reload, 300) }} />
          )}
          {creating === null && !topic && !loading && (
            <div className="rounded-[20px] bg-hatch border border-white/[0.04] flex flex-col items-center gap-2 py-16 text-center px-6">
              <FlaskConical className="h-6 w-6 text-overlay1" />
              <p className="text-sm text-subtext0">Start your first research run</p>
              <p className="text-[11px] text-overlay1 max-w-sm">Mayday searches, saves every source, checks each quote against its source and writes cited answers.</p>
            </div>
          )}
          {topic && creating === null && (
            <>
              <header className="space-y-3">
                <div className="flex flex-wrap items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <h1 className="text-lg font-medium text-text truncate">{topic}</h1>
                    {run && (
                      <p className="text-xs text-overlay1">
                        <span className={statusTone(run.status)}>{run.status}</span>
                        {' · '}{run.usage.sources} new sources · {run.usage.llm_calls} model calls · ${run.usage.cost_usd.toFixed(3)}
                        {run.error ? ` · ${run.error}` : ''}
                      </p>
                    )}
                  </div>
                  <RunPicker runs={runs} runId={runId} onPick={setRunId} />
                  <button onClick={() => setCreating(topic)} className="rounded-full px-3 py-1.5 text-xs text-subtext0 hover:bg-white/[0.04]">Run again</button>
                  {run && run.status !== 'running' && run.answers.length > 0 && (
                    <div className="flex gap-1">
                      <button onClick={copyBibtex} title="Copy BibTeX for the cited sources"
                              className="flex items-center gap-1 rounded-full bg-white/[0.06] px-3 py-1.5 text-xs text-subtext1 hover:bg-white/[0.1]">
                        {copied ? <Check className="h-3 w-3 text-green" /> : <BookMarked className="h-3 w-3" />}{copied ? 'Copied' : 'BibTeX'}
                      </button>
                      {([['md', FileText, 'Report'], ['docx', FileText, 'Word'], ['xlsx', FileSpreadsheet, 'Excel'],
                         ['tex', FileCode2, 'LaTeX']] as const).map(([f, Icon, label]) => (
                        <button key={f} onClick={() => doExport(f)} disabled={!!exporting}
                                className="flex items-center gap-1 rounded-full bg-white/[0.06] px-3 py-1.5 text-xs text-subtext1 hover:bg-white/[0.1] disabled:opacity-50">
                          {exporting === f ? <Loader2 className="h-3 w-3 animate-spin" /> : <Icon className="h-3 w-3" />}{label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {run && <StageProgress run={run} />}
              </header>

              {!runs.length && !runError && (
                <p className="text-sm text-overlay1">This topic has no evidence-checked runs yet. Use “Run again” to start one.</p>
              )}
              {runError && runs.length === 0 && <p className="text-sm text-overlay1">This topic has no evidence-checked runs yet.</p>}

              {run && (
                <>
                  <div role="tablist" className="flex gap-1 border-b border-white/[0.06]">
                    {TABS.filter(t => t.id !== 'hypotheses' || (run.hypotheses?.length ?? 0) > 0).map(t => (
                      <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
                              className={cn('px-3 py-2 text-sm -mb-px border-b-2',
                                tab === t.id ? 'border-green text-text' : 'border-transparent text-subtext0 hover:text-text')}>
                        {t.label}
                      </button>
                    ))}
                  </div>
                  <section role="tabpanel">
                    {tab === 'answers' && <AnswersView run={run} />}
                    {tab === 'hypotheses' && <HypothesesView run={run} />}
                    {tab === 'evidence' && <EvidenceView claims={evidence.claims} loading={evidence.loading} />}
                    {tab === 'sources' && <SourcesView sources={evidence.sources} loading={evidence.loading} />}
                    {tab === 'log' && <RunLogView run={run} />}
                  </section>
                </>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  )
}
