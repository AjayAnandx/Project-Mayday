import { useMemo } from 'react'
import type { Event } from '../../types/event'
import { DayCell } from './DayCell'

interface MonthGridProps {
  year: number
  month: number
  events: Event[]
  onDayClick: (date: string) => void
}

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export function MonthGrid({ year, month, events, onDayClick }: MonthGridProps) {
  const today = new Date()

  const { firstDay, daysInMonth, prevDaysInMonth } = useMemo(() => {
    const first = new Date(year, month, 1).getDay()
    const days = new Date(year, month + 1, 0).getDate()
    const prevDays = new Date(year, month, 0).getDate()
    return { firstDay: first, daysInMonth: days, prevDaysInMonth: prevDays }
  }, [year, month])

  const cells = useMemo(() => {
    const result: { day: number; isCurrentMonth: boolean; dateStr: string }[] = []

    for (let i = firstDay - 1; i >= 0; i--) {
      const day = prevDaysInMonth - i
      result.push({
        day,
        isCurrentMonth: false,
        dateStr: `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`,
      })
    }

    for (let day = 1; day <= daysInMonth; day++) {
      result.push({
        day,
        isCurrentMonth: true,
        dateStr: `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`,
      })
    }

    const remaining = 42 - result.length
    for (let day = 1; day <= remaining; day++) {
      const nextMonth = month + 1 > 11 ? 0 : month + 1
      const nextYear = month + 1 > 11 ? year + 1 : year
      result.push({
        day,
        isCurrentMonth: false,
        dateStr: `${nextYear}-${String(nextMonth + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`,
      })
    }

    return result
  }, [firstDay, daysInMonth, prevDaysInMonth, year, month])

  const eventsByDate = useMemo(() => {
    const map = new Map<string, Event[]>()
    for (const ev of events) {
      const dateKey = ev.start_time.slice(0, 10)
      if (!map.has(dateKey)) map.set(dateKey, [])
      map.get(dateKey)!.push(ev)
    }
    return map
  }, [events])

  const isToday = (dateStr: string) => {
    const t = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
    return dateStr === t
  }

  return (
    <div className="flex flex-col">
      <div className="grid grid-cols-7 mb-0.5 sm:mb-1">
        {DAYS.map((d) => (
          <div key={d} className="text-center text-[10px] sm:text-xs font-medium text-overlay0 py-0.5 sm:py-1">
            <span className="sm:hidden">{d.slice(0, 2)}</span>
            <span className="hidden sm:inline">{d}</span>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-[1px] sm:gap-0.5">
        {cells.map((cell, i) => (
          <DayCell
            key={i}
            day={cell.day}
            isToday={isToday(cell.dateStr)}
            isCurrentMonth={cell.isCurrentMonth}
            events={eventsByDate.get(cell.dateStr) || []}
            onClick={() => onDayClick(cell.dateStr)}
          />
        ))}
      </div>
    </div>
  )
}
