import { useState, useEffect } from 'react'
import type { Todo, TodoCreate, TodoUpdate } from '../../types/todo'
import { Modal } from '../ui/Modal'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { Button } from '../ui/Button'

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

  useEffect(() => {
    if (todo) {
      setTitle(todo.title)
      setDescription(todo.description)
      setDueDate(todo.due_date || '')
      setPriority(String(todo.priority))
      setTags(todo.tags.join(', '))
    } else {
      setTitle('')
      setDescription('')
      setDueDate('')
      setPriority('2')
      setTags('')
    }
  }, [todo, open])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const data = {
      title,
      description,
      due_date: dueDate || null,
      priority: Number(priority),
      tags: tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
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
