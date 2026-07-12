import { useState, useEffect, useRef } from 'react'
import type { Event, EventCreate, EventUpdate, RecurrenceRule } from '../../types/event'
import { Modal } from '../ui/Modal'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { Button } from '../ui/Button'
import { Checkbox } from '../ui/Checkbox'
import { api } from '../../services/api'

interface EventDialogProps {
  open: boolean
  onClose: () => void
  onSave: (data: EventCreate | EventUpdate) => void
  onDelete?: (id: string) => void
  event?: Event | null
  defaultDate?: string
}

export function EventDialog({ open, onClose, onSave, onDelete, event, defaultDate }: EventDialogProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [allDay, setAllDay] = useState(false)
  const [recPattern, setRecPattern] = useState('')
  const [recInterval, setRecInterval] = useState('1')
  const [recEndDate, setRecEndDate] = useState('')
  const [recCount, setRecCount] = useState('')

  const [duplicates, setDuplicates] = useState<Event[]>([])
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

  const checkDuplicates = (t: string, s: string) => {
    if (!t.trim() || event) {
      setDuplicates([])
      return
    }
    api.checkEventDuplicates(t, s).then(setDuplicates).catch(() => setDuplicates([]))
  }

  useEffect(() => {
    if (event) {
      setTitle(event.title)
      setDescription(event.description)
      setStartTime(event.start_time.slice(0, 16))
      setEndTime(event.end_time.slice(0, 16))
      setAllDay(event.all_day)
      setRecPattern(event.recurrence?.pattern || '')
      setRecInterval(String(event.recurrence?.interval ?? 1))
      setRecEndDate(event.recurrence?.end_date || '')
      setRecCount(String(event.recurrence?.count ?? ''))
    } else {
      setTitle('')
      setDescription('')
      const date = defaultDate || new Date().toISOString().slice(0, 10)
      setStartTime(`${date}T09:00`)
      setEndTime(`${date}T10:00`)
      setAllDay(false)
      setRecPattern('')
      setRecInterval('1')
      setRecEndDate('')
      setRecCount('')
    }
    setDuplicates([])
  }, [event, open, defaultDate])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => checkDuplicates(title, startTime), 400)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [title, startTime])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const recurrence: RecurrenceRule | undefined = recPattern
      ? {
          pattern: recPattern as RecurrenceRule['pattern'],
          ...(recInterval !== '1' ? { interval: Number(recInterval) } : {}),
          ...(recEndDate ? { end_date: recEndDate } : {}),
          ...(recCount ? { count: Number(recCount) } : {}),
        }
      : undefined
    const data = {
      title,
      description,
      start_time: allDay ? startTime.slice(0, 10) + 'T00:00:00' : startTime + ':00',
      end_time: allDay ? endTime.slice(0, 10) + 'T23:59:00' : endTime + ':00',
      all_day: allDay,
      recurrence,
    }
    onSave(data)
    onClose()
  }

  return (
    <Modal open={open} onClose={onClose} title={event ? 'Edit Event' : 'New Event'}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <Input
          label="Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          autoFocus
        />
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-subtext0">Description</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full rounded-xl bg-surface0/50 px-4 py-2.5 text-sm text-text placeholder-overlay0 border border-surface1 focus:border-green/50 focus:outline-none focus:ring-1 focus:ring-green/20 transition-all outline-none resize-none h-20"
          />
        </div>
        <Checkbox
          label="All day"
          checked={allDay}
          onChange={() => setAllDay(!allDay)}
        />
        <Input
          label={allDay ? 'Date' : 'Start Time'}
          type={allDay ? 'date' : 'datetime-local'}
          value={startTime}
          onChange={(e) => setStartTime(e.target.value)}
          required
        />
        {!allDay && (
          <Input
            label="End Time"
            type="datetime-local"
            value={endTime}
            onChange={(e) => setEndTime(e.target.value)}
            required
          />
        )}

        {duplicates.length > 0 && (
          <div className="rounded-xl bg-yellow/10 border border-yellow/30 px-3 py-2">
            <p className="text-xs font-semibold text-yellow mb-1">⚠️ Potential duplicate{duplicates.length > 1 ? 's' : ''}</p>
            {duplicates.slice(0, 3).map(d => (
              <p key={d.id} className="text-xs text-subtext0">
                '{d.title}' — {d.start_time.slice(0, 16)} → {d.end_time.slice(0, 16)}
              </p>
            ))}
            {duplicates.length > 3 && <p className="text-xs text-subtext0 mt-1">+{duplicates.length - 3} more</p>}
          </div>
        )}

        <div className="border-t border-surface1/50 pt-3">
          <p className="text-xs font-medium text-subtext0 mb-2">Recurrence</p>
          <Select
            label="Pattern"
            value={recPattern}
            onChange={(e) => setRecPattern(e.target.value)}
            options={[
              { value: '', label: 'None' },
              { value: 'daily', label: 'Daily' },
              { value: 'weekly', label: 'Weekly' },
              { value: 'biweekly', label: 'Biweekly' },
              { value: 'monthly', label: 'Monthly' },
              { value: 'yearly', label: 'Yearly' },
            ]}
          />
          {recPattern && (
            <div className="flex flex-col sm:flex-row gap-2 mt-2">
              <div className="w-full sm:w-24 flex flex-col gap-1.5">
                <label className="text-xs font-medium text-subtext0">Interval</label>
                <input
                  type="number"
                  min={1}
                  value={recInterval}
                  onChange={(e) => setRecInterval(e.target.value)}
                  className="w-full rounded-xl bg-surface0/50 px-3 py-2.5 text-sm text-text placeholder-overlay0 border border-surface1 focus:border-green/50 focus:outline-none focus:ring-1 focus:ring-green/20 transition-all outline-none"
                />
              </div>
              <div className="flex-1 flex flex-col gap-1.5">
                <label className="text-xs font-medium text-subtext0">End Date</label>
                <input
                  type="date"
                  value={recEndDate}
                  onChange={(e) => setRecEndDate(e.target.value)}
                  className="w-full rounded-xl bg-surface0/50 px-3 py-2.5 text-sm text-text placeholder-overlay0 border border-surface1 focus:border-green/50 focus:outline-none focus:ring-1 focus:ring-green/20 transition-all outline-none"
                />
              </div>
              <div className="w-full sm:w-24 flex flex-col gap-1.5">
                <label className="text-xs font-medium text-subtext0">Max Count</label>
                <input
                  type="number"
                  min={1}
                  value={recCount}
                  onChange={(e) => setRecCount(e.target.value)}
                  className="w-full rounded-xl bg-surface0/50 px-3 py-2.5 text-sm text-text placeholder-overlay0 border border-surface1 focus:border-green/50 focus:outline-none focus:ring-1 focus:ring-green/20 transition-all outline-none"
                />
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-col sm:flex-row justify-between mt-2 gap-2 sm:gap-0">
          <div>
            {event && onDelete && (
              <Button
                type="button"
                variant="danger"
                onClick={() => {
                  onDelete(event.id)
                  onClose()
                }}
                className="w-full sm:w-auto"
              >
                Delete
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit">{event ? 'Update' : 'Create'}</Button>
          </div>
        </div>
      </form>
    </Modal>
  )
}
