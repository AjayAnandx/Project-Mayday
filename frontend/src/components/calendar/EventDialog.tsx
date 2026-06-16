import { useState, useEffect } from 'react'
import type { Event, EventCreate, EventUpdate } from '../../types/event'
import { Modal } from '../ui/Modal'
import { Input } from '../ui/Input'
import { Button } from '../ui/Button'
import { Checkbox } from '../ui/Checkbox'

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

  useEffect(() => {
    if (event) {
      setTitle(event.title)
      setDescription(event.description)
      setStartTime(event.start_time.slice(0, 16))
      setEndTime(event.end_time.slice(0, 16))
      setAllDay(event.all_day)
    } else {
      setTitle('')
      setDescription('')
      const date = defaultDate || new Date().toISOString().slice(0, 10)
      setStartTime(`${date}T09:00`)
      setEndTime(`${date}T10:00`)
      setAllDay(false)
    }
  }, [event, open, defaultDate])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const data = {
      title,
      description,
      start_time: allDay ? startTime.slice(0, 10) + 'T00:00:00' : startTime + ':00',
      end_time: allDay ? endTime.slice(0, 10) + 'T23:59:00' : endTime + ':00',
      all_day: allDay,
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
        <div className="flex justify-between mt-2">
          <div>
            {event && onDelete && (
              <Button
                type="button"
                variant="danger"
                onClick={() => {
                  onDelete(event.id)
                  onClose()
                }}
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
