import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, ClipboardList, Plus, Check } from 'lucide-react'

interface Pack {
  id: string; title: string; starts_at: string; opened_at: string | null
  content: { briefing: string[]; changed: string[]; raise: string[]; action_items: string[] }
  sources: { n: number; kind: string; text: string }[]
}
interface Friction { key: string; kind: string; severity: string; day: string; title: string }

const KIND_LABEL: Record<string, string> = {
  conflict: 'Clash', overload: 'Overloaded day', unscheduled: 'No time set aside',
  missing_prep: 'Prep missing', waiting_risk: 'Waiting on someone',
}

function when(s: string) {
  const d = new Date(s.length <= 10 ? `${s}T00:00` : s)
  return isNaN(d.getTime()) ? s : d.toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: s.length > 10 ? '2-digit' : undefined, minute: s.length > 10 ? '2-digit' : undefined })
}

function Section({ title, items }: { title: string; items: string[] }) {
  if (!items?.length) return null
  return (
    <div className="mt-2">
      <p className="text-[11px] font-semibold text-subtext1">{title}</p>
      <ul className="mt-0.5 space-y-0.5">{items.map((l, i) => <li key={i} className="text-xs text-text">• {l}</li>)}</ul>
    </div>
  )
}

function PackCard({ p }: { p: Pack }) {
  const [open, setOpen] = useState(false)
  const [added, setAdded] = useState<Set<number>>(new Set())
  const toggle = async () => {
    if (!open && !p.opened_at) { try { await fetch(`/api/brain/prep/${p.id}`) } catch { /* ignore */ } }
    setOpen(o => !o)
  }
  const add = async (i: number) => {
    const r = await fetch(`/api/brain/prep/${p.id}/action/${i}`, { method: 'POST' })
    if (r.ok) { setAdded(s => new Set(s).add(i)); window.dispatchEvent(new CustomEvent('planner-changed')) }
  }
  return (
    <li className="rounded-xl border border-blue-400/30 bg-blue-400/5 px-3 py-2">
      <button onClick={toggle} aria-expanded={open} className="w-full flex items-center gap-2 text-left">
        {open ? <ChevronDown className="h-3.5 w-3.5 text-overlay1" /> : <ChevronRight className="h-3.5 w-3.5 text-overlay1" />}
        <ClipboardList className="h-3.5 w-3.5 text-blue-400" />
        <span className="text-sm text-text flex-1 min-w-0 truncate">{p.title}</span>
        <span className="text-[11px] text-overlay0">{when(p.starts_at)}</span>
      </button>
      {open && (
        <div className="pl-6 pb-1">
          <Section title="Briefing" items={p.content.briefing} />
          <Section title="What changed" items={p.content.changed} />
          <Section title="To raise" items={p.content.raise} />
          {p.content.action_items?.length > 0 && (
            <div className="mt-2">
              <p className="text-[11px] font-semibold text-subtext1">Action items</p>
              <ul className="mt-0.5 space-y-1">
                {p.content.action_items.map((a, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-text">
                    <span className="flex-1">• {a}</span>
                    <button disabled={added.has(i)} onClick={() => add(i)}
                      className="shrink-0 flex items-center gap-1 text-[11px] text-green hover:underline disabled:text-overlay0 disabled:no-underline">
                      {added.has(i) ? <><Check className="h-3 w-3" /> added</> : <><Plus className="h-3 w-3" /> Planner</>}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <details className="mt-2">
            <summary className="text-[11px] text-overlay1 cursor-pointer">Sources ({p.sources.length})</summary>
            <ol className="mt-1 space-y-0.5">{p.sources.map(s => <li key={s.n} className="text-[11px] text-overlay1">[{s.n}] {s.text}</li>)}</ol>
          </details>
        </div>
      )}
    </li>
  )
}

export function PrepAndFriction() {
  const [packs, setPacks] = useState<Pack[]>([])
  const [fr, setFr] = useState<Friction[]>([])
  const load = useCallback(async () => {
    try {
      const [p, f] = await Promise.all([fetch('/api/brain/prep').then(r => r.json()), fetch('/api/brain/frictions').then(r => r.json())])
      setPacks(p.packs ?? []); setFr(f.frictions ?? [])
    } catch { /* shown as empty */ }
  }, [])
  useEffect(() => { load() }, [load])
  if (!packs.length && !fr.length) return null
  return (
    <>
      {packs.length > 0 && (
        <section aria-labelledby="prep-h">
          <h3 id="prep-h" className="text-xs font-semibold text-subtext1 mb-2">Prepared for you</h3>
          <ul className="space-y-1.5">{packs.map(p => <PackCard key={p.id} p={p} />)}</ul>
        </section>
      )}
      {fr.length > 0 && (
        <section aria-labelledby="fr-h">
          <h3 id="fr-h" className="text-xs font-semibold text-subtext1 mb-2">Coming up (next 3 days)</h3>
          <ul className="space-y-1.5">
            {fr.map(f => (
              <li key={f.key} className={`rounded-xl border px-3 py-2 ${f.severity === 'high' ? 'border-red/30 bg-red/5' : 'border-yellow/30 bg-yellow/5'}`}>
                <p className="flex items-center gap-1.5 text-[11px] font-semibold text-subtext1">
                  <AlertTriangle className={`h-3 w-3 ${f.severity === 'high' ? 'text-red' : 'text-yellow'}`} />
                  {KIND_LABEL[f.kind] ?? f.kind} · {when(f.day)}
                </p>
                <p className="text-sm text-text mt-0.5">{f.title}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}
