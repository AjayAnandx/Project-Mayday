import { useState, useEffect, useRef } from 'react'
import type { Todo, TodoCreate, TodoUpdate, RecurrenceRule } from '../../types/todo'
import { Modal } from '../ui/Modal'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { Button } from '../ui/Button'
import { api } from '../../services/api'

interface TodoDialogProps {
  open: boolean
  onClose: () => void
  onSave: (data: TodoCreate | TodoUpdate) => void
  todo?: Todo | null
}

export function TodoDialog({ open, onClose, onSave, todo }: TodoDialogProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [priority, setPriority] = useState('2')
  const [tags, setTags] = useState('')
  const [recPattern, setRecPattern] = useState('')
  const [recInterval, setRecInterval] = useState('1')
  const [recEndDate, setRecEndDate] = useState('')
  const [recCount, setRecCount] = useState('')

  const [duplicates, setDuplicates] = useState<Todo[]>([])
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

  const checkDuplicates = (t: string, d: string) => {
    if (!t.trim() || todo) {
      setDuplicates([])
      return
    }
    api.checkTodoDuplicates(t, d || undefined).then(setDuplicates).catch(() => setDuplicates([]))
  }

  useEffect(() => {
    if (todo) {
      setTitle(todo.title)
      setDescription(todo.description)
      setDueDate(todo.due_date || '')
      setPriority(String(todo.priority))
      setTags(todo.tags.join(', '))
      setRecPattern(todo.recurrence?.pattern || '')
      setRecInterval(String(todo.recurrence?.interval ?? 1))
      setRecEndDate(todo.recurrence?.end_date || '')
      setRecCount(String(todo.recurrence?.count ?? ''))
    } else {
      setTitle('')
      setDescription('')
      setDueDate('')
      setPriority('2')
      setTags('')
      setRecPattern('')
      setRecInterval('1')
      setRecEndDate('')
      setRecCount('')
    }
    setDuplicates([])
  }, [todo, open])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => checkDuplicates(title, dueDate), 400)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [title, dueDate])

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
      due_date: dueDate || null,
      priority: Number(priority),
      tags: tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
      recurrence,
    }
    onSave(data)
    onClose()
  }

  return (
    <Modal open={open} onClose={onClose} title={todo ? 'Edit Todo' : 'New Todo'}>
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
        <Input
          label="Due Date"
          type="date"
          value={dueDate}
          onChange={(e) => setDueDate(e.target.value)}
        />
        <Select
          label="Priority"
          value={priority}
          onChange={(e) => setPriority(e.target.value)}
          options={[
            { value: '1', label: 'High' },
            { value: '2', label: 'Medium' },
            { value: '3', label: 'Low' },
          ]}
        />
        <Input
          label="Tags (comma separated)"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
        />

        {duplicates.length > 0 && (
          <div className="rounded-xl bg-yellow/10 border border-yellow/30 px-3 py-2">
            <p className="text-xs font-semibold text-yellow mb-1">⚠️ Potential duplicate{duplicates.length > 1 ? 's' : ''}</p>
            {duplicates.slice(0, 3).map(d => (
              <p key={d.id} className="text-xs text-subtext0">
                '{d.title}' — {d.completed ? '✓ done' : '○ pending'}{d.due_date ? ` (due: ${d.due_date})` : ''}
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
            <div className="flex gap-2 mt-2">
              <div className="w-24 flex flex-col gap-1.5">
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
              <div className="w-24 flex flex-col gap-1.5">
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

        <div className="flex justify-end gap-2 mt-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit">{todo ? 'Update' : 'Create'}</Button>
        </div>
      </form>
    </Modal>
  )
}
