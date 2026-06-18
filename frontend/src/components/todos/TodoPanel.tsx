import { useState } from 'react'
import { ListTodo, Plus, Search } from 'lucide-react'
import { useTodos } from '../../hooks/useTodos'
import { TodoItem } from './TodoItem'
import { TodoDialog } from './TodoDialog'
import { Button } from '../ui/Button'
import { useChatContext } from '../../context/ChatContext'
import type { Todo, TodoCreate, TodoUpdate } from '../../types/todo'

export function TodoPanel() {
  const { toolCallCount } = useChatContext()
  const {
    todos,
    loading,
    search,
    setSearch,
    showCompleted,
    setShowCompleted,
    createTodo,
    updateTodo,
    deleteTodo,
    toggleTodo,
  } = useTodos(toolCallCount)

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingTodo, setEditingTodo] = useState<Todo | null>(null)

  const handleSave = async (data: TodoCreate | TodoUpdate) => {
    if (editingTodo) {
      await updateTodo(editingTodo.id, data as TodoUpdate)
    } else {
      await createTodo(data as TodoCreate)
    }
  }

  const handleEdit = (todo: Todo) => {
    setEditingTodo(todo)
    setDialogOpen(true)
  }

  const handleAdd = () => {
    setEditingTodo(null)
    setDialogOpen(true)
  }

  return (
    <div className="flex flex-col h-full max-w-3xl mx-auto w-full">
      <div className="p-6 pb-4 bg-crust">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-green/15 flex items-center justify-center">
              <ListTodo className="h-5 w-5 text-green" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-text">Todos</h1>
              <p className="text-xs text-overlay0">Manage your tasks</p>
            </div>
          </div>
          <Button onClick={handleAdd} className="gap-1.5">
            <Plus className="h-4 w-4" />
            Add Todo
          </Button>
        </div>

        <div className="flex items-center gap-3 mb-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-overlay0" />
            <input
              placeholder="Search todos..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-xl bg-black/40 pl-10 pr-4 py-2.5 text-sm text-text placeholder-overlay0 border border-white/10 focus:border-green/50 focus:outline-none focus:ring-1 focus:ring-green/20 transition-all"
            />
          </div>
          <label className="flex items-center gap-2 cursor-pointer shrink-0">
            <input
              type="checkbox"
              checked={showCompleted}
              onChange={() => setShowCompleted(!showCompleted)}
              className="w-4 h-4 rounded bg-surface0 border-surface1 text-green focus:ring-green/20"
            />
            <span className="text-xs text-subtext0">Show completed</span>
          </label>
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
        ) : todos.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-overlay0">
            <ListTodo className="h-10 w-10 mb-3 opacity-40" />
            <p className="text-sm font-medium">No todos yet</p>
            <p className="text-xs mt-1">{search ? 'No matching todos' : 'Click "Add Todo" to create one'}</p>
          </div>
        ) : (
          <div className="space-y-0.5">
            {todos.map((todo) => (
              <TodoItem
                key={todo.id}
                todo={todo}
                onToggle={toggleTodo}
                onEdit={handleEdit}
                onDelete={deleteTodo}
              />
            ))}
          </div>
        )}
      </div>

      <TodoDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSave={handleSave}
        todo={editingTodo}
      />
    </div>
  )
}
