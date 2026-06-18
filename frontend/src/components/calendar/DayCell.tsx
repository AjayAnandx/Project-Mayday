import { Repeat } from 'lucide-react'
import type { Event } from '../../types/event'

interface DayCellProps {
  day: number
  isToday: boolean
  isCurrentMonth: boolean
  events: Event[]
  onClick: () => void
}

export function DayCell({ day, isToday, isCurrentMonth, events, onClick }: DayCellProps) {
  return (
    <button
      onClick={onClick}
      className={`relative flex flex-col items-center pt-1.5 pb-1 rounded-xl transition-all min-h-[68px] ${
        !isCurrentMonth
          ? 'text-overlay0/30'
          : 'text-text hover:bg-surface0/40'
      } ${isToday ? 'bg-green/10 ring-1 ring-green/30' : ''}`}
    >
      <span className={`text-xs font-semibold mb-0.5 ${isToday ? 'text-green' : ''}`}>
        {day}
      </span>
      <div className="flex flex-col gap-0.5 w-full px-1">
        {events.slice(0, 2).map((ev) => (
          <div
            key={ev.id}
            className="text-[8px] leading-tight truncate rounded-md px-1 py-0.5 bg-green/15 text-green font-medium flex items-center gap-0.5"
            title={ev.title}
          >
            {ev.recurrence && <Repeat className="h-2.5 w-2.5 shrink-0" />}
            <span className="truncate">{ev.title}</span>
          </div>
        ))}
        {events.length > 2 && (
          <span className="text-[9px] text-overlay0 font-medium">+{events.length - 2}</span>
        )}
      </div>
    </button>
  )
}
