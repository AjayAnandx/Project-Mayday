import { useState, useMemo } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'
import { useEvents } from '../../hooks/useEvents'
import { MonthGrid } from './MonthGrid'
import { EventDialog } from './EventDialog'
import type { Event, EventCreate, EventUpdate } from '../../types/event'

export function CalendarPanel() {
  const { events, loading, createEvent, updateEvent, deleteEvent } = useEvents()
  const [currentDate, setCurrentDate] = useState(() => new Date())
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingEvent, setEditingEvent] = useState<Event | null>(null)
  const [selectedDate, setSelectedDate] = useState('')

  const year = currentDate.getFullYear()
  const month = currentDate.getMonth()

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
      <div className="p-6 pb-4 bg-crust">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-green/15 flex items-center justify-center">
              <CalendarDays className="h-5 w-5 text-green" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-text">Calendar</h1>
              <p className="text-xs text-overlay0">Your events at a glance</p>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <button
            onClick={handlePrev}
            className="p-2 rounded-lg text-overlay0 hover:text-text hover:bg-surface0/50 transition-colors"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
          <h2 className="text-lg font-semibold bg-gradient-to-r from-green to-green/60 bg-clip-text text-transparent">{monthName}</h2>
          <button
            onClick={handleNext}
            className="p-2 rounded-lg text-overlay0 hover:text-text hover:bg-surface0/50 transition-colors"
          >
            <ChevronRight className="h-5 w-5" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-6">
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
