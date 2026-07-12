import { Pencil, Trash2, Circle, CheckCircle2, Repeat } from 'lucide-react'
import type { Todo } from '../../types/todo'
import { Badge } from '../ui/Badge'

interface TodoItemProps {
  todo: Todo
  onToggle: (id: string, completed: boolean) => void
  onEdit: (todo: Todo) => void
  onDelete: (id: string) => void
}

const priorityLabel = { 1: 'High', 2: 'Med', 3: 'Low' } as const
const priorityVariant = { 1: 'high', 2: 'medium', 3: 'low' } as const

const recLabel: Record<string, string> = {
  daily: 'Daily',
  weekly: 'Weekly',
  biweekly: 'Biweekly',
  monthly: 'Monthly',
  yearly: 'Yearly',
}

export function TodoItem({ todo, onToggle, onEdit, onDelete }: TodoItemProps) {
  return (
    <div
      className={`group flex items-start gap-2 sm:gap-3 p-2.5 sm:p-3.5 rounded-xl transition-all hover:bg-surface0/30 ${
        todo.completed ? 'opacity-50' : ''
      }`}
    >
      <button
        onClick={() => onToggle(todo.id, !todo.completed)}
        className="mt-0.5 shrink-0 text-overlay0 hover:text-green transition-colors"
      >
        {todo.completed
          ? <CheckCircle2 className="h-5 w-5 text-green" />
          : <Circle className="h-5 w-5" />
        }
      </button>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span
            className={`text-sm font-medium ${
              todo.completed ? 'line-through text-overlay0' : 'text-text'
            }`}
          >
            {todo.title}
          </span>
          <Badge variant={priorityVariant[todo.priority as keyof typeof priorityVariant]}>
            {priorityLabel[todo.priority as keyof typeof priorityLabel]}
          </Badge>
        </div>

        {todo.description && (
          <p className="text-xs text-overlay0 mt-1 line-clamp-1">{todo.description}</p>
        )}

        <div className="flex items-center gap-2 mt-1.5">
          {todo.recurrence && (
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-green/15 text-green flex items-center gap-1">
              <Repeat className="h-3 w-3" />
              {recLabel[todo.recurrence.pattern] || todo.recurrence.pattern}
            </span>
          )}
          {todo.due_date && (
            <span className="text-[11px] text-subtext0 bg-surface0/50 px-2 py-0.5 rounded-full">
              Due {new Date(todo.due_date).toLocaleDateString()}
            </span>
          )}
          {todo.tags.map((tag) => (
            <span
              key={tag}
              className="text-[11px] px-2 py-0.5 rounded-full bg-green/10 text-green"
            >
              #{tag}
            </span>
          ))}
        </div>
      </div>

      <div className="flex gap-0.5 opacity-60 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
        <button
          onClick={() => onEdit(todo)}
          className="p-1.5 rounded-lg text-overlay0 hover:text-text hover:bg-surface0/50 transition-colors"
          title="Edit"
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => onDelete(todo.id)}
          className="p-1.5 rounded-lg text-overlay0 hover:text-red hover:bg-red/10 transition-colors"
          title="Delete"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}
