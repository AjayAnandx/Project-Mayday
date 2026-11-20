import { useState } from 'react'
import { Check, Clock, Hourglass, Mail, Plus } from 'lucide-react'
import { cn } from '../../lib/utils'
import { fmtWhen, toLocalStr, todayStr } from '../../lib/planner'
import { usePlannerActions } from '../../hooks/usePlanner'
import type { NudgeResult, Person, PlannerItem } from '../../types/planner'

/** Everything other people owe the user, grouped by person, with chase tools. */
export function WaitingBoard({ items, people, onOpen, onNew }: {
  items: PlannerItem[]
  people: Person[]
  onOpen: (i: PlannerItem) => void
  onNew: () => void
}) {
  const actions = usePlannerActions()
  const [nudges, setNudges] = useState<Record<string, NudgeResult>>({})
  const groups = new Map<string, PlannerItem[]>()
  for (const it of items) groups.set(it.person_id ?? '', [...(groups.get(it.person_id ?? '') ?? []), it])

  const pushFollowUp = (it: PlannerItem, days: number) => {
    const d = new Date()
    d.setDate(d.getDate() + days)
    d.setHours(9, 0, 0, 0)
    return actions.update(it.id, { follow_up_at: toLocalStr(d) })
  }

  if (items.length === 0) {
    return (
      <div className="rounded-[20px] bg-hatch border border-white/[0.04] flex flex-col items-center justify-center gap-2 py-16 text-center">
        <Hourglass className="h-6 w-6 text-overlay1" />
        <p className="text-sm text-subtext0">Nobody owes you anything right now</p>
        <p className="text-[11px] text-overlay1 max-w-xs">Track work you've handed off — type <span className="text-subtext1">"Ravi to send the deck by friday"</span> in the bar above, or tell Mayday.</p>
        <button onClick={onNew} className="mt-2 flex items-center gap-1.5 rounded-xl bg-green/10 border border-green/25 px-3 py-1.5 text-xs text-green hover:bg-green/15">
          <Plus className="h-3.5 w-3.5" /> Add waiting-on
        </button>
      </div>
    )
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
      {[...groups.entries()].map(([pid, list]) => {
        const person = people.find(p => p.id === pid)
        return (
          <section key={pid} className="rounded-[20px] bg-[#0b0b0b] border border-white/[0.06] p-4">
            <header className="flex items-center gap-3 mb-3">
              <span className="w-9 h-9 rounded-full bg-gradient-to-br from-[#86efac] to-[#16a34a] flex items-center justify-center text-black text-sm font-bold">
                {(person?.name ?? '?').slice(0, 1).toUpperCase()}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm text-text truncate">{person?.name ?? 'Unknown'}</p>
                <p className="text-[11px] text-overlay1 truncate">{person?.email || 'no email saved'} · owes {list.length}</p>
              </div>
            </header>
            <ul className="space-y-2">
              {list.map(it => {
                const due = it.follow_up_at && it.follow_up_at.slice(0, 10) <= todayStr()
                const n = nudges[it.id]
                return (
                  <li key={it.id} className="rounded-2xl bg-white/[0.03] border border-white/[0.05] p-3">
                    <button onClick={() => onOpen(it)} className="block w-full text-left">
                      <p className="text-sm text-text">{it.title}</p>
                      <p className="flex flex-wrap gap-x-2 mt-1 text-[11px] text-overlay1">
                        {it.due_at && <span>due {fmtWhen(it.due_at)}</span>}
                        {it.follow_up_at && (
                          <span className={cn('flex items-center gap-1', due && 'text-yellow')}>
                            <Clock className="h-3 w-3" />follow up {fmtWhen(it.follow_up_at)}
                          </span>
                        )}
                        {it.chase_log.length > 0 && <span>chased {it.chase_log.length}×</span>}
                      </p>
                    </button>
                    <div className="flex flex-wrap gap-1.5 mt-2.5">
                      <button
                        onClick={async () => { const r = await actions.nudge(it.id); setNudges(s => ({ ...s, [it.id]: r })) }}
                        className="flex items-center gap-1 rounded-lg bg-green/10 border border-green/25 px-2 py-1 text-[11px] text-green hover:bg-green/15">
                        <Mail className="h-3 w-3" /> Draft nudge
                      </button>
                      <button onClick={() => pushFollowUp(it, 2)}
                              className="rounded-lg bg-white/[0.04] px-2 py-1 text-[11px] text-subtext0 hover:bg-white/[0.08]">+2 days</button>
                      <button onClick={() => actions.complete(it.id)}
                              className="flex items-center gap-1 rounded-lg bg-white/[0.04] px-2 py-1 text-[11px] text-subtext0 hover:bg-white/[0.08]">
                        <Check className="h-3 w-3" /> Received
                      </button>
                    </div>
                    {n && (
                      <p className={cn('mt-2 text-[11px]', n.drafted ? 'text-green' : 'text-yellow')}>
                        {n.drafted ? `Draft saved in Gmail → ${n.to}` : `Not drafted: ${n.reason}`}
                      </p>
                    )}
                  </li>
                )
              })}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
