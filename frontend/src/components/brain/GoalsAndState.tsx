import { useCallback, useEffect, useState } from 'react'
import { Target, Check, X } from 'lucide-react'

interface Intent { id: string; goal: string; p: number; status: string; horizon: string | null; implies: string[] }
interface State {
  focus: number; load: number; fatigue: number; stress: number
  reasons: Record<string, string[]>; calibrating: string[]
}
const DIMS: { key: keyof Omit<State, 'reasons' | 'calibrating'>; label: string; low: number }[] = [
  { key: 'focus', label: 'Focus', low: 0.3 }, { key: 'load', label: 'Workload', low: 0.3 },
  { key: 'fatigue', label: 'Tiredness', low: 0.3 }, { key: 'stress', label: 'Pressure', low: 0.3 },
]

export function GoalsAndState() {
  const [intents, setIntents] = useState<Intent[]>([])
  const [state, setState] = useState<State | null>(null)
  const load = useCallback(async () => {
    try {
      const [i, s] = await Promise.all([fetch('/api/brain/intents').then(r => r.json()), fetch('/api/brain/state').then(r => r.json())])
      setIntents(i.intents ?? []); setState(s)
    } catch { /* empty */ }
  }, [])
  useEffect(() => { load() }, [load])

  const verdict = async (id: string, v: 'confirm' | 'reject') => {
    await fetch(`/api/brain/intents/${id}/${v}`, { method: 'POST' }); load()
  }
  const correct = async (dim: string, value: number) => {
    const r = await fetch('/api/brain/state/correct', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dim, value }) })
    if (r.ok) setState(await r.json())
  }

  return (
    <>
      {intents.length > 0 && (
        <section aria-labelledby="goals-h">
          <h3 id="goals-h" className="text-xs font-semibold text-subtext1 mb-2">What I think you're working towards</h3>
          <ul className="space-y-1.5">
            {intents.map(it => (
              <li key={it.id} className="rounded-xl border border-surface1 bg-surface0/60 px-3 py-2">
                <div className="flex items-start gap-2">
                  <Target className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${it.status === 'hypothesis' ? 'text-overlay1' : 'text-green'}`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-text">{it.goal}{it.horizon && <span className="text-[11px] text-overlay0"> · by {it.horizon}</span>}</p>
                    <p className="text-[11px] text-overlay1">
                      {it.status === 'confirmed' ? 'you confirmed this' : `${Math.round(it.p * 100)}% sure`}
                      {it.implies?.length ? ` · needs: ${it.implies.join(', ')}` : ''}
                    </p>
                  </div>
                  {it.status !== 'confirmed' && (
                    <div className="flex gap-1 shrink-0">
                      <button onClick={() => verdict(it.id, 'confirm')} title="Yes, that's it" aria-label="Confirm" className="p-1.5 rounded-full text-green hover:bg-green/10"><Check className="h-3.5 w-3.5" /></button>
                      <button onClick={() => verdict(it.id, 'reject')} title="Not right" aria-label="Not right" className="p-1.5 rounded-full text-overlay1 hover:text-red hover:bg-red/10"><X className="h-3.5 w-3.5" /></button>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {state && (
        <section aria-labelledby="state-h">
          <h3 id="state-h" className="text-xs font-semibold text-subtext1 mb-1">My read of your day</h3>
          <p className="text-[11px] text-overlay0 mb-2">Compared with your own usual days. Used only to adjust how and when I speak; correct me if it's off.</p>
          <ul className="space-y-2">
            {DIMS.map(d => {
              const v = state[d.key]
              const reasons = state.reasons?.[d.key] ?? []
              const cal = state.calibrating?.includes(d.key)
              return (
                <li key={d.key}>
                  <div className="flex items-center gap-2">
                    <span className="w-20 text-xs text-subtext1">{d.label}</span>
                    <div className="flex-1 h-1.5 rounded-full bg-surface1 overflow-hidden" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v * 100)} aria-label={d.label}>
                      <div className={`h-full rounded-full ${v >= 0.7 ? 'bg-yellow' : 'bg-green'}`} style={{ width: `${Math.round(v * 100)}%` }} />
                    </div>
                    {v >= d.low && (
                      <button onClick={() => correct(d.key, 0.1)} className="text-[11px] text-overlay1 hover:text-text">Not right</button>
                    )}
                  </div>
                  {(reasons.length > 0 || cal) && (
                    <p className="pl-[5.5rem] text-[11px] text-overlay0">{reasons.join(' · ')}{cal ? `${reasons.length ? ' · ' : ''}still learning your baseline` : ''}</p>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </>
  )
}
