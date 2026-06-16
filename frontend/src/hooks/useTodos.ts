import { useState, useEffect, useCallback } from 'react'
import type { Todo, TodoCreate, TodoUpdate } from '../types/todo'
import { api } from '../services/api'

export function useTodos() {
  const [todos, setTodos] = useState<Todo[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [showCompleted, setShowCompleted] = useState(true)

  const fetchTodos = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.listTodos(showCompleted, search)
      setTodos(data)
    } catch (err) {
      console.error('Failed to fetch todos:', err)
    } finally {
      setLoading(false)
    }
  }, [showCompleted, search])

  useEffect(() => {
    fetchTodos()
  }, [fetchTodos])

  const createTodo = async (data: TodoCreate) => {
    await api.createTodo(data)
    await fetchTodos()
  }

  const updateTodo = async (id: string, data: TodoUpdate) => {
    await api.updateTodo(id, data)
    await fetchTodos()
  }

  const deleteTodo = async (id: string) => {
    await api.deleteTodo(id)
    await fetchTodos()
  }

  const toggleTodo = async (id: string, completed: boolean) => {
    await api.updateTodo(id, { completed })
    await fetchTodos()
  }

  return {
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
    refresh: fetchTodos,
  }
}
