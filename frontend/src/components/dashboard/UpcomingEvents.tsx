import { Bell, CalendarDays, CalendarPlus, Hourglass, ListTodo } from 'lucide-react'
import { cn } from '../../lib/utils'
import { anchorOf, fmtTime, hasTime, itemKey, parseLocal, todayStr } from '../../lib/planner'
import type { PlannerItem } from '../../types/planner'
import { DashCard, CardHeader } from './DashCard'

const KIND = {
  event: { icon: CalendarDays, label: '' },
  task: { icon: ListTodo, label: 'Task' },
  reminder: { icon: Bell, label: 'Reminder' },
  waiting: { icon: Hourglass, label: 'Follow up' },
} as const

/** Agenda: events + dated tasks/follow-ups for the next 7 days, from the Planner. */
export function UpcomingEvents({ items, onOpen, className }: {
  items: PlannerItem[]
  onOpen?: () => void
  className?: string
}) {
  const today = todayStr()

  return (
    <DashCard className={className}>
      <CardHeader title="Agenda · next 7 days" icon={CalendarDays} onOpen={onOpen} />

      {items.length === 0 ? (
        <div className="flex-1 rounded-2xl bg-hatch border border-white/[0.04] flex flex-col items-center justify-center gap-2 py-8 text-center">
          <CalendarPlus className="h-5 w-5 text-overlay1" />
          <p className="text-sm text-subtext0">Your week is clear</p>
          <p className="text-[11px] text-overlay1">Ask Mayday to schedule something.</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {items.map(it => {
            const when = anchorOf(it) ?? today
            const start = parseLocal(when)
            const isToday = when.slice(0, 10) === today
            const k = KIND[it.kind]
            return (
              <li key={itemKey(it)}
                  className="flex items-center gap-3 rounded-2xl bg-white/[0.03] border border-white/[0.05] p-2.5 hover:bg-white/[0.05] transition-colors">
                <div className={cn('w-12 h-12 shrink-0 rounded-xl flex flex-col items-center justify-center leading-none',
                  isToday ? 'bg-green text-black' : 'bg-white/[0.05] text-text')}>
                  <span className="text-lg font-semibold tabular-nums">{start.getDate()}</span>
                  <span className={cn('text-[9px] uppercase mt-0.5', isToday ? 'text-black/70' : 'text-overlay1')}>
                    {start.toLocaleDateString(undefined, { weekday: 'short' })}
                  </span>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-text truncate">{it.title}</p>
                  <p className="flex items-center gap-1.5 text-[11px] text-overlay1 mt-0.5">
                    {it.kind !== 'event' && <k.icon className="h-3 w-3" />}
                    {k.label && <span>{k.label} ·</span>}
                    {hasTime(when)
                      ? `${fmtTime(when)}${it.kind === 'event' && it.end_at && hasTime(it.end_at) ? ` – ${fmtTime(it.end_at)}` : ''}`
                      : it.kind === 'event' ? 'All day' : 'Any time'}
                  </p>
                </div>
                {isToday && (
                  <span className="shrink-0 rounded-md bg-green/15 text-green px-1.5 py-0.5 text-[10px] font-semibold">Today</span>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </DashCard>
  )
}
