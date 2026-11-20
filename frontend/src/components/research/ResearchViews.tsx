import { useMemo, useState } from 'react'
import { Check, CircleDashed, ExternalLink, Loader2, X } from 'lucide-react'
import { cn } from '../../lib/utils'
import {
  RUN_STAGES, type Claim, type ClaimStatus, type CitedSource, type RunDetail, type Source, type SourceTier,
} from '../../types/research-run'

const TIER_STYLE: Record<SourceTier, string> = {
  primary: 'bg-green/15 text-green',
  secondary: 'bg-yellow/15 text-yellow',
  tertiary: 'bg-white/[0.06] text-subtext0',
  unknown: 'bg-white/[0.04] text-overlay1',
}

const STATUS_STYLE: Record<ClaimStatus, string> = {
  supported: 'bg-green/15 text-green',
  contested: 'bg-yellow/15 text-yellow',
  unsupported: 'bg-red/15 text-red',
  unverified: 'bg-white/[0.06] text-subtext0',
}

const STATUS_BADGE: Record<string, { label: string; cls: string; title: string }> = {
  peer_reviewed: { label: 'peer reviewed', cls: 'bg-green/10 text-green', title: 'Published after peer or editorial review' },
  preprint: { label: 'preprint', cls: 'bg-yellow/15 text-yellow', title: 'Not yet peer reviewed' },
  retracted: { label: 'retracted', cls: 'bg-red/20 text-red', title: 'Retracted: never used as evidence' },
}

/** Peer-reviewed / preprint / retracted / open-access badges for scholarly sources. */
export function StatusBadge({ status, oa }: { status?: string | null; oa?: boolean }) {
  const s = status ? STATUS_BADGE[status] : undefined
  return (
    <>
      {s && <span title={s.title} className={cn('rounded-md px-1.5 py-0.5 text-[10px] font-medium', s.cls)}>{s.label}</span>}
      {oa && <span title="Open access" className="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-subtext0">OA</span>}
    </>
  )
}

function scholarlyLine(s: { authors?: string[]; venue?: string; year?: number | string | null; doi?: string | null; arxiv_id?: string | null }) {
  const who = s.authors?.length ? `${s.authors[0].split(' ').slice(-1)[0]}${s.authors.length > 1 ? ' et al.' : ''}` : ''
  return [who, s.year, s.venue, s.doi ? `doi:${s.doi}` : s.arxiv_id ? `arXiv:${s.arxiv_id}` : ''].filter(Boolean).join(' · ')
}

export function TierBadge({ tier }: { tier: SourceTier | null | undefined }) {
  const t = (tier ?? 'unknown') as SourceTier
  return <span className={cn('rounded-md px-1.5 py-0.5 text-[10px] font-medium', TIER_STYLE[t])}>{t}</span>
}

function hostOf(url: string | null | undefined) {
  if (!url) return ''
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url }
}

/** Live stage progress for a run (8 steps). */
export function StageProgress({ run }: { run: RunDetail }) {
  const done = new Map(run.stages.map(s => [s.stage, s]))
  // run.stage is the last *finished* stage; the one after it is in progress.
  const currentIdx = run.stages.length ? RUN_STAGES.indexOf(run.stage as typeof RUN_STAGES[number]) + 1 : 0
  return (
    <ol className="flex flex-wrap gap-1.5" aria-label="Research stages">
      {RUN_STAGES.map((stage, idx) => {
        const entry = done.get(stage)
        const current = run.status === 'running' && !entry && idx === currentIdx
        return (
          <li key={stage} title={entry?.notes}
              className={cn('flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] capitalize',
                entry ? (entry.passed ? 'bg-green/10 text-green' : 'bg-yellow/10 text-yellow')
                  : current ? 'bg-white/[0.08] text-text' : 'bg-white/[0.03] text-overlay1')}>
            {entry ? (entry.passed ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />)
              : current ? <Loader2 className="h-3 w-3 animate-spin" /> : <CircleDashed className="h-3 w-3" />}
            {stage}
          </li>
        )
      })}
    </ol>
  )
}

/** Answer text with [n] references turned into links to the cited source. */
function CitedText({ text, sources }: { text: string; sources: CitedSource[] }) {
  const parts = text.split(/(\[\d+\])/g)
  return (
    <p className="text-sm leading-relaxed text-subtext1">
      {parts.map((part, i) => {
        const m = part.match(/^\[(\d+)\]$/)
        if (!m) return <span key={i}>{part}</span>
        const src = sources.find(s => s.n === Number(m[1]))
        return (
          <a key={i} href={src?.url} target="_blank" rel="noreferrer" title={src ? `${src.title} — ${hostOf(src.url)}` : ''}
             className="align-super text-[10px] font-semibold text-green hover:underline mx-px">{part}</a>
        )
      })}
    </p>
  )
}

export function AnswersView({ run }: { run: RunDetail }) {
  if (!run.answers?.length) {
    return <p className="text-sm text-overlay1">{run.status === 'running' ? 'Answers appear when the run reaches the synthesize stage.' : 'This run produced no answers.'}</p>
  }
  return (
    <div className="space-y-6">
      {run.brief?.scope && <p className="text-xs text-overlay1">Scope: {run.brief.scope}</p>}
      {run.answers.map((a, i) => (
        <section key={i} className="space-y-2">
          <h3 className="text-sm font-medium text-text">{i + 1}. {a.question}</h3>
          {a.rendered
            ? <CitedText text={a.rendered} sources={run.cited_sources} />
            : <p className="text-sm italic text-overlay1">Not enough verified evidence to answer this question.</p>}
          {a.dropped_sentences > 0 && (
            <p className="text-[11px] text-overlay1">{a.dropped_sentences} sentence{a.dropped_sentences > 1 ? 's' : ''} without a verified source removed.</p>
          )}
        </section>
      ))}
      {((run.gaps?.length ?? 0) > 0 || (run.review?.length ?? 0) > 0) && (
        <section className="rounded-2xl border border-white/[0.06] p-4 space-y-1.5">
          <h3 className="text-xs font-medium text-yellow">Gaps and limitations</h3>
          {run.gaps?.map((g, i) => <p key={`g${i}`} className="text-xs text-subtext0">No verified evidence for: {g}</p>)}
          {run.review?.map((r, i) => <p key={`r${i}`} className="text-xs text-subtext0">Reviewer: {r}</p>)}
        </section>
      )}
      {run.cited_sources.length > 0 && (
        <section className="space-y-1.5">
          <h3 className="text-xs font-medium text-subtext0">Cited sources</h3>
          <ol className="space-y-1">
            {run.cited_sources.map(s => (
              <li key={s.id} className="flex items-baseline gap-2 text-xs">
                <span className="w-6 shrink-0 text-right text-overlay1 tabular-nums">[{s.n}]</span>
                <a href={s.url} target="_blank" rel="noreferrer" className="text-subtext1 hover:text-green truncate">{s.title || s.url}</a>
                <span className="text-overlay1 shrink-0">{scholarlyLine(s) || hostOf(s.url)}</span>
                <StatusBadge status={s.evidence_status} oa={s.is_oa} />
                <TierBadge tier={s.tier} />
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  )
}

const FILTERS: (ClaimStatus | 'all')[] = ['all', 'supported', 'contested', 'unsupported']

export function EvidenceView({ claims, loading }: { claims: Claim[]; loading: boolean }) {
  const [filter, setFilter] = useState<ClaimStatus | 'all'>('supported')
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: claims.length }
    for (const x of claims) c[x.status] = (c[x.status] ?? 0) + 1
    return c
  }, [claims])
  const shown = filter === 'all' ? claims : claims.filter(c => c.status === filter)
  if (loading && !claims.length) return <p className="text-sm text-overlay1">Loading evidence…</p>
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map(f => (
          <button key={f} onClick={() => setFilter(f)}
                  className={cn('rounded-full px-3 py-1 text-xs capitalize', filter === f ? 'bg-white/[0.1] text-text' : 'text-subtext0 hover:bg-white/[0.04]')}>
            {f} <span className="text-overlay1 tabular-nums">{counts[f] ?? 0}</span>
          </button>
        ))}
      </div>
      {filter === 'unsupported' && shown.length > 0 && (
        <p className="text-[11px] text-overlay1">These quotes were not found in their source, so they are never used in answers.</p>
      )}
      {!shown.length && <p className="text-sm text-overlay1">No {filter === 'all' ? '' : filter} claims.</p>}
      <ul className="space-y-2">
        {shown.map(c => (
          <li key={c.id} className="rounded-2xl border border-white/[0.06] p-3 space-y-2">
            <div className="flex items-start gap-2">
              <p className="flex-1 text-sm text-text">{c.statement}</p>
              <span className={cn('rounded-md px-1.5 py-0.5 text-[10px] font-medium shrink-0', STATUS_STYLE[c.status])}>{c.status}</span>
            </div>
            {c.quote && <blockquote className="border-l-2 border-white/[0.1] pl-3 text-xs italic text-subtext0">“{c.quote}”</blockquote>}
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-overlay1">
              <span className="flex items-center gap-1.5" title={c.confidence_reasons.join('; ')}>
                <span className="h-1.5 w-16 rounded-full bg-white/[0.06] overflow-hidden">
                  <span className="block h-full bg-green" style={{ width: `${Math.round(c.confidence * 100)}%` }} />
                </span>
                {c.confidence.toFixed(2)}
              </span>
              {c.source.url && (
                <a href={c.source.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 hover:text-green">
                  <ExternalLink className="h-3 w-3" />{c.source.title || hostOf(c.source.url)}
                </a>
              )}
              <TierBadge tier={c.source.tier} />
              <StatusBadge status={c.source.evidence_status} />
              {c.as_of && <span>as of {c.as_of}</span>}
            </div>
            {(c.study || c.evidence_level) && (
              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                {c.evidence_level && (
                  <span title="Evidence level: study design, replication, peer review, contradictions"
                        className={cn('rounded-md px-1.5 py-0.5 font-medium',
                          c.evidence_level === 'strong' ? 'bg-green/15 text-green'
                            : c.evidence_level === 'moderate' ? 'bg-green/10 text-green'
                            : c.evidence_level === 'retracted' ? 'bg-red/20 text-red' : 'bg-white/[0.06] text-subtext0')}>
                    evidence: {c.evidence_level}
                  </span>
                )}
                {c.study?.design && <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-subtext1">{c.study.design.replace(/_/g, ' ')}</span>}
                {c.study?.dataset && <span className="text-overlay1">data: {c.study.dataset}</span>}
                {c.study?.sample_n && <span className="text-overlay1">n = {c.study.sample_n}</span>}
                {c.study?.effect?.value && (
                  <span className="text-overlay1">{c.study.effect.metric || 'effect'} {c.study.effect.value}{c.study.effect.ci ? ` (${c.study.effect.ci})` : ''}</span>
                )}
                {c.study?.p_value && <span className="text-overlay1">p = {c.study.p_value}</span>}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function SourcesView({ sources, loading }: { sources: Source[]; loading: boolean }) {
  if (loading && !sources.length) return <p className="text-sm text-overlay1">Loading sources…</p>
  if (!sources.length) return <p className="text-sm text-overlay1">No sources saved yet.</p>
  const sorted = [...sources].sort((a, b) => b.verified_claims - a.verified_claims)
  return (
    <ul className="divide-y divide-white/[0.05]">
      {sorted.map(s => (
        <li key={s.id} className="flex items-center gap-3 py-2">
          <div className="flex-1 min-w-0">
            <a href={s.url} target="_blank" rel="noreferrer" className="block truncate text-sm text-subtext1 hover:text-green">{s.title || s.url}</a>
            {scholarlyLine(s) && <p className="truncate text-[11px] text-subtext0">{scholarlyLine(s)}</p>}
            <p className="truncate text-[11px] text-overlay1">
              {hostOf(s.url)} · {s.type}{s.published_date ? ` · ${s.published_date}` : ''}
              {' · '}{s.access === 'ok' ? 'full text' : s.access === 'snippet' ? 'snippet only' : s.access ?? 'not fetched'}
            </p>
          </div>
          <StatusBadge status={s.evidence_status} oa={s.is_oa} />
          <TierBadge tier={s.tier} />
          <span className="w-20 text-right text-[11px] text-overlay1 tabular-nums">{s.verified_claims} verified</span>
        </li>
      ))}
    </ul>
  )
}

function Meter({ label, used, max, fmt }: { label: string; used: number; max: number; fmt: (n: number) => string }) {
  const pct = max ? Math.min(100, Math.round((used / max) * 100)) : 0
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[11px]"><span className="text-subtext0">{label}</span>
        <span className="text-overlay1 tabular-nums">{fmt(used)} / {fmt(max)}</span></div>
      <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden"><div className="h-full bg-green" style={{ width: `${pct}%` }} /></div>
    </div>
  )
}

export function RunLogView({ run }: { run: RunDetail }) {
  const minutes = run.finished_at
    ? (new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 60000
    : (Date.now() - new Date(run.started_at).getTime()) / 60000
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <Meter label="Time" used={minutes} max={run.budget.max_minutes} fmt={n => `${n.toFixed(1)} min`} />
        <Meter label="New sources" used={run.usage.sources} max={run.budget.max_sources} fmt={n => `${Math.round(n)}`} />
        <Meter label="Cost" used={run.usage.cost_usd} max={run.budget.max_cost_usd} fmt={n => `$${n.toFixed(3)}`} />
      </div>
      <table className="w-full text-xs">
        <thead><tr className="text-left text-overlay1"><th className="py-1 pr-3 font-normal">Stage</th><th className="py-1 pr-3 font-normal">Gate</th><th className="py-1 font-normal">Notes</th></tr></thead>
        <tbody className="divide-y divide-white/[0.05]">
          {run.stages.map((s, i) => (
            <tr key={i}>
              <td className="py-1.5 pr-3 capitalize text-subtext1">{s.stage}</td>
              <td className={cn('py-1.5 pr-3', s.passed ? 'text-green' : 'text-yellow')}>{s.passed ? 'passed' : 'not met'}</td>
              <td className="py-1.5 text-subtext0">{s.notes}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <SelectionPanel run={run} />
      {run.models && <p className="text-[11px] text-overlay1">Models: {Object.entries(run.models).map(([k, v]) => `${k} ${v}`).join(' · ')}</p>}
      {run.error && <p className="text-xs text-yellow">{run.error}</p>}
    </div>
  )
}

const SELECTION_STEPS: [string, string][] = [
  ['identified', 'Records found by the searches'], ['duplicates_or_known', 'Duplicates or already saved'],
  ['snowball_added', 'Added by following citations'], ['excluded_retracted', 'Excluded: retracted'],
  ['screened', 'Screened'], ['over_budget', 'Not fetched: over budget'], ['fetch_failed', 'Not retrievable'],
  ['abstract_or_snippet_only', 'Abstract / snippet only'], ['full_text', 'Full text read'],
  ['included', 'Included as sources'], ['no_relevant_claims', 'Read, no relevant evidence'],
]

/** PRISMA-style search and selection counts + inclusion criteria + search log. */
function SelectionPanel({ run }: { run: RunDetail }) {
  const sel = run.selection ?? {}
  const steps = SELECTION_STEPS.filter(([k]) => typeof sel[k] === 'number' && (sel[k] as number) > 0)
  const crit = run.brief?.criteria
  const retracted = (sel.retracted_titles as string[] | undefined) ?? []
  if (!steps.length && !crit && !run.search_log?.length) return null
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-medium text-subtext0">Search and selection</h3>
      {steps.length > 0 && (
        <ul className="grid gap-x-6 gap-y-1 sm:grid-cols-2 text-xs">
          {steps.map(([k, label]) => (
            <li key={k} className="flex justify-between gap-3">
              <span className="text-subtext0">{label}</span><span className="tabular-nums text-subtext1">{sel[k] as number}</span>
            </li>
          ))}
        </ul>
      )}
      {retracted.length > 0 && <p className="text-[11px] text-red">Excluded as retracted: {retracted.join('; ')}</p>}
      {crit && (crit.include?.length || crit.exclude?.length) ? (
        <p className="text-[11px] text-overlay1">
          Inclusion: {(crit.include ?? []).join('; ') || '-'} · Exclusion: {(crit.exclude ?? []).join('; ') || '-'}
        </p>
      ) : null}
      {run.search_log?.length ? (
        <details className="text-[11px] text-overlay1">
          <summary className="cursor-pointer text-subtext0">{run.search_log.length} searches</summary>
          <ul className="mt-1 space-y-0.5">
            {run.search_log.map((q, i) => <li key={i}>{q.kind}: “{q.query}” — {q.results} results</li>)}
          </ul>
        </details>
      ) : null}
    </section>
  )
}

const VERDICT_STYLE: Record<string, string> = {
  supported: 'bg-green/15 text-green', refuted: 'bg-red/15 text-red',
  inconclusive: 'bg-yellow/15 text-yellow', untested: 'bg-white/[0.06] text-subtext0',
}

/** Hypotheses with verdicts computed from verified, level-weighted evidence. */
export function HypothesesView({ run }: { run: RunDetail }) {
  const hyps = run.hypotheses ?? []
  if (!hyps.length) return <p className="text-sm text-overlay1">This run tested no hypotheses.</p>
  return (
    <div className="space-y-3">
      <p className="text-[11px] text-overlay1">
        Verdicts count only verified claims, weighted by evidence level (strong 3 · moderate 2 · limited 1 · weak 0.5).
        Answered hypotheses are frozen; new ideas become new hypotheses.
      </p>
      {hyps.map(h => (
        <section key={h.id} className="rounded-2xl border border-white/[0.06] p-3 space-y-2">
          <div className="flex items-start gap-2">
            <span className="text-[11px] text-overlay1 tabular-nums pt-0.5">{h.label}</span>
            <p className="flex-1 text-sm text-text">{h.statement}</p>
            <span className={cn('rounded-md px-1.5 py-0.5 text-[10px] font-medium shrink-0', VERDICT_STYLE[h.verdict ?? 'untested'])}>
              {h.verdict ?? 'untested'}
            </span>
          </div>
          <p className="text-[11px] text-overlay1 tabular-nums">For {h.support ?? 0} · against {h.refute ?? 0}</p>
          {h.claims?.length ? (
            <ul className="space-y-1">
              {h.claims.map(c => (
                <li key={c.claim_id} className="flex gap-2 text-xs">
                  <span className={cn('shrink-0', c.stance === 'supports' ? 'text-green' : 'text-red')}>{c.stance}</span>
                  <span className="text-subtext1">{c.statement}</span>
                  {c.level && <span className="shrink-0 text-overlay1">({c.level})</span>}
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ))}
    </div>
  )
}
