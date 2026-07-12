import { CalendarDays, Clock } from 'lucide-react'
import type { Event } from '../../types/event'

interface UpcomingEventsProps {
  events: Event[]
}

export function UpcomingEvents({ events }: UpcomingEventsProps) {
  if (events.length === 0) {
    return (
      <div className="rounded-xl bg-surface0/40 border border-surface1/50 p-4 sm:p-5">
        <div className="flex items-center gap-2 mb-3">
          <CalendarDays className="h-4 w-4 text-green" />
          <h3 className="text-sm font-semibold text-text">Upcoming Events</h3>
        </div>
        <p className="text-xs text-overlay0">No upcoming events in the next 7 days</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl bg-surface0/40 border border-surface1/50 p-4 sm:p-5">
      <div className="flex items-center gap-2 mb-3">
        <CalendarDays className="h-4 w-4 text-green" />
        <h3 className="text-sm font-semibold text-text">Upcoming Events</h3>
      </div>
      <div className="space-y-1.5">
        {events.map((ev) => (
          <div key={ev.id} className="flex items-center gap-3 p-2 rounded-lg hover:bg-surface1/30 transition-colors">
            <div className="w-1.5 h-1.5 rounded-full bg-green shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm text-text truncate">{ev.title}</p>
              <p className="text-[11px] text-overlay0 flex items-center gap-1 mt-0.5">
                <Clock className="h-3 w-3" />
                {new Date(ev.start_time).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}
                {' '}
                {ev.all_day ? 'All day' : `${new Date(ev.start_time).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
