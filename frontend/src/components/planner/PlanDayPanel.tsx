import { useState } from 'react'
import { Check, Sparkles, X } from 'lucide-react'
import { api } from '../../services/api'
import { usePlannerActions } from '../../hooks/usePlanner'
import { fmtTime } from '../../lib/planner'
import type { DayPlan } from '../../types/planner'

/** "Plan my day": propose time blocks for open tasks; nothing is saved until accepted. */
export function PlanDayPanel() {
  const actions = usePlannerActions()
  const [plan, setPlan] = useState<DayPlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [accepted, setAccepted] = useState<Set<string>>(new Set())

  const propose = async () => {
    setBusy(true)
    try {
      setPlan(await api.planner.planDay())
      setAccepted(new Set())
    } finally {
      setBusy(false)
    }
  }

  const accept = async (ids: string[]) => {
    if (!plan) return
    for (const b of plan.blocks.filter(b => ids.includes(b.item_id))) {
      await actions.schedule(b.item_id, b.start, b.end)
    }
    setAccepted(prev => new Set([...prev, ...ids]))
  }

  if (!plan) {
    return (
      <button onClick={propose} disabled={busy}
              className="flex items-center gap-2 rounded-xl bg-green/10 border border-green/25 px-3 py-2 text-xs font-medium text-green hover:bg-green/15 disabled:opacity-60">
        <Sparkles className="h-3.5 w-3.5" /> {busy ? 'Planning…' : 'Plan my day'}
      </button>
    )
  }

  const pending = plan.blocks.filter(b => !accepted.has(b.item_id))
  return (
    <div className="rounded-[20px] border border-green/30 bg-gradient-to-br from-green/[0.08] to-transparent p-4">
      <div className="flex items-center justify-between gap-2 mb-3">
        <p className="flex items-center gap-2 text-sm text-text"><Sparkles className="h-4 w-4 text-green" /> {plan.summary}</p>
        <button onClick={() => setPlan(null)} aria-label="Close plan" className="p-1 rounded-full text-overlay1 hover:text-text"><X className="h-4 w-4" /></button>
      </div>
      {plan.blocks.length > 0 && (
        <ul className="space-y-1.5 mb-3">
          {plan.blocks.map(b => (
            <li key={b.item_id} className="flex items-center gap-3 rounded-xl bg-white/[0.03] px-3 py-2">
              <span className="text-[11px] text-green tabular-nums w-28 shrink-0">{fmtTime(b.start)} – {fmtTime(b.end)}</span>
              <span className="flex-1 text-sm text-text truncate">{b.title}</span>
              {accepted.has(b.item_id)
                ? <span className="flex items-center gap-1 text-[11px] text-green"><Check className="h-3 w-3" /> blocked</span>
                : <button onClick={() => accept([b.item_id])} className="text-[11px] text-subtext0 hover:text-green">Accept</button>}
            </li>
          ))}
        </ul>
      )}
      {plan.unplaced.length > 0 && <p className="text-[11px] text-overlay1 mb-3">Didn't fit: {plan.unplaced.map(u => u.title).join(', ')}</p>}
      {pending.length > 0 && (
        <button onClick={() => accept(pending.map(b => b.item_id))}
                className="rounded-xl bg-green text-black text-xs font-semibold px-3 py-1.5 hover:bg-green/90">Accept all {pending.length}</button>
      )}
    </div>
  )
}
