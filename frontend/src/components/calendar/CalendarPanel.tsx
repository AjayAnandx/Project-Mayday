import { useState, useMemo } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'
import { useEvents } from '../../hooks/useEvents'
import { MonthGrid } from './MonthGrid'
import { EventDialog } from './EventDialog'
import { useChatContext } from '../../context/ChatContext'
import type { Event, EventCreate, EventUpdate } from '../../types/event'

export function CalendarPanel() {
  const [currentDate, setCurrentDate] = useState(() => new Date())
  const year = currentDate.getFullYear()
  const month = currentDate.getMonth()
  const monthStart = `${year}-${String(month + 1).padStart(2, '0')}-01`
  const monthEnd = `${year}-${String(month + 1).padStart(2, '0')}-${new Date(year, month + 1, 0).getDate()}`
  const { toolCallCount } = useChatContext()
  const { events, loading, createEvent, updateEvent, deleteEvent } = useEvents(monthStart, monthEnd, toolCallCount)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingEvent, setEditingEvent] = useState<Event | null>(null)
  const [selectedDate, setSelectedDate] = useState('')

  const monthName = useMemo(
    () =>
      new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(currentDate),
    [currentDate],
  )

  const handlePrev = () => setCurrentDate(new Date(year, month - 1, 1))
  const handleNext = () => setCurrentDate(new Date(year, month + 1, 1))

  const handleDayClick = (date: string) => {
    setEditingEvent(null)
    setSelectedDate(date)
    setDialogOpen(true)
  }

  const handleSave = async (data: EventCreate | EventUpdate) => {
    if (editingEvent) {
      await updateEvent(editingEvent.id, data as EventUpdate)
    } else {
      await createEvent(data as EventCreate)
    }
  }

  return (
    <div className="flex flex-col h-full max-w-3xl mx-auto w-full">
      <div className="p-4 sm:p-6 pb-4 bg-crust">
        <div className="flex items-center justify-between mb-4 sm:mb-6">
          <div className="flex items-center gap-2 sm:gap-3">
            <div className="w-8 sm:w-10 h-8 sm:h-10 rounded-xl bg-green/15 flex items-center justify-center shrink-0">
              <CalendarDays className="h-4 sm:h-5 w-4 sm:w-5 text-green" />
            </div>
            <div>
              <h1 className="text-base sm:text-xl font-bold text-text">Calendar</h1>
              <p className="text-[10px] sm:text-xs text-overlay0 hidden sm:block">Your events at a glance</p>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <button
            onClick={handlePrev}
            className="p-1.5 sm:p-2 rounded-lg text-overlay0 hover:text-text hover:bg-surface0/50 transition-colors"
          >
            <ChevronLeft className="h-4 sm:h-5 w-4 sm:w-5" />
          </button>
          <h2 className="text-sm sm:text-lg font-semibold bg-gradient-to-r from-green to-green/60 bg-clip-text text-transparent truncate mx-1 sm:mx-0">{monthName}</h2>
          <button
            onClick={handleNext}
            className="p-1.5 sm:p-2 rounded-lg text-overlay0 hover:text-text hover:bg-surface0/50 transition-colors"
          >
            <ChevronRight className="h-4 sm:h-5 w-4 sm:w-5" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 sm:px-6 pb-4 sm:pb-6">
        {loading ? (
          <div className="flex items-center justify-center h-48 text-subtext0 text-sm">
            <div className="flex flex-col items-center gap-2">
              <div className="w-5 h-5 border-2 border-surface1 border-t-green rounded-full animate-spin" />
              <span>Loading...</span>
            </div>
          </div>
        ) : (
          <MonthGrid
            year={year}
            month={month}
            events={events}
            onDayClick={handleDayClick}
          />
        )}
      </div>

      <EventDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSave={handleSave}
        onDelete={deleteEvent}
        event={editingEvent}
        defaultDate={selectedDate}
      />
    </div>
  )
}
