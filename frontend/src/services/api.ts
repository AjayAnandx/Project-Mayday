import type { Todo, TodoCreate, TodoUpdate } from '../types/todo'
import type { Event, EventCreate, EventUpdate } from '../types/event'
import type { GraphData, GraphNode } from '../types/graph'

const BASE = '/api'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  // Todos
  listTodos: (includeCompleted = true, q = '') =>
    request<Todo[]>(`/todos?include_completed=${includeCompleted}&q=${encodeURIComponent(q)}`),

  createTodo: (data: TodoCreate) =>
    request<Todo>('/todos', { method: 'POST', body: JSON.stringify(data) }),

  updateTodo: (id: string, data: TodoUpdate) =>
    request<Todo>(`/todos/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteTodo: (id: string) =>
    request<{ deleted: boolean }>(`/todos/${id}`, { method: 'DELETE' }),

  // Events
  listEvents: (startDate = '', endDate = '', q = '') =>
    request<Event[]>(`/events?start_date=${startDate}&end_date=${endDate}&q=${encodeURIComponent(q)}`),

  createEvent: (data: EventCreate) =>
    request<Event>('/events', { method: 'POST', body: JSON.stringify(data) }),

  updateEvent: (id: string, data: EventUpdate) =>
    request<Event>(`/events/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteEvent: (id: string) =>
    request<{ deleted: boolean }>(`/events/${id}`, { method: 'DELETE' }),

  // Memory Graph
  fetchGraph: () =>
    request<GraphData>('/memory/graph'),

  searchGraph: (q: string) =>
    request<GraphData>(`/memory/graph/search?q=${encodeURIComponent(q)}`),

  fetchNode: (id: string) =>
    request<{ node: GraphNode; subgraph: GraphData }>(`/memory/graph/node/${id}`),
}
