import { CalendarDays, CalendarPlus } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { Event } from '../../types/event'
import { DashCard, CardHeader } from './DashCard'

function sameDay(a: Date, b: Date) {
  return a.toDateString() === b.toDateString()
}

export function UpcomingEvents({ events, onOpen, className }: {
  events: Event[]
  onOpen?: () => void
  className?: string
}) {
  const now = new Date()

  return (
    <DashCard className={className}>
      <CardHeader
        title="Agenda · next 7 days"
        icon={CalendarDays}
        onOpen={onOpen}
      />

      {events.length === 0 ? (
        <div className="flex-1 rounded-2xl bg-hatch border border-white/[0.04] flex flex-col items-center justify-center gap-2 py-8 text-center">
          <CalendarPlus className="h-5 w-5 text-overlay1" />
          <p className="text-sm text-subtext0">Your week is clear</p>
          <p className="text-[11px] text-overlay1">Ask Mayday to schedule something.</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {events.map(ev => {
            const start = new Date(ev.start_time)
            const today = sameDay(start, now)
            return (
              <li
                key={ev.id}
                className="flex items-center gap-3 rounded-2xl bg-white/[0.03] border border-white/[0.05] p-2.5 hover:bg-white/[0.05] transition-colors"
              >
                <div
                  className={cn(
                    'w-12 h-12 shrink-0 rounded-xl flex flex-col items-center justify-center leading-none',
                    today ? 'bg-green text-black' : 'bg-white/[0.05] text-text',
                  )}
                >
                  <span className="text-lg font-semibold tabular-nums">{start.getDate()}</span>
                  <span className={cn('text-[9px] uppercase mt-0.5', today ? 'text-black/70' : 'text-overlay1')}>
                    {start.toLocaleDateString(undefined, { weekday: 'short' })}
                  </span>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-text truncate">{ev.title}</p>
                  <p className="text-[11px] text-overlay1 mt-0.5">
                    {ev.all_day
                      ? 'All day'
                      : `${start.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}${
                          ev.end_time
                            ? ` – ${new Date(ev.end_time).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`
                            : ''}`}
                  </p>
                </div>
                {today && (
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
