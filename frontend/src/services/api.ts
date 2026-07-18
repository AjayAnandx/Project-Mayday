import type { Todo, TodoCreate, TodoUpdate } from '../types/todo'
import type { Event, EventCreate, EventUpdate } from '../types/event'
import type { GraphData, GraphNode } from '../types/graph'
import type { SearchResults } from '../types/search'
import type { DashboardData, DashboardWeather, AiNewsResponse } from '../types/dashboard'
import type { DocumentMeta } from '../types/document'

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
  // Documents
  listDocuments: () =>
    request<DocumentMeta[]>('/documents'),

  getDocument: (id: string) =>
    request<DocumentMeta>(`/documents/${id}`),

  getDocumentText: (id: string, pages?: string) =>
    request<{ doc_id: string; text: string }>(`/documents/${id}/text${pages ? `?pages=${encodeURIComponent(pages)}` : ''}`),

  searchDocuments: (q: string, limit = 10) =>
    request<DocumentMeta[]>(`/documents/search?q=${encodeURIComponent(q)}&limit=${limit}`),

  uploadDocument: async (file: File): Promise<DocumentMeta> => {
    const formData = new FormData()
    formData.append('file', file)
    const res = await fetch(`${BASE}/documents`, {
      method: 'POST',
      body: formData,
    })
    if (!res.ok) {
      const err = await res.text()
      throw new Error(err || `HTTP ${res.status}`)
    }
    return res.json()
  },

  deleteDocument: (id: string) =>
    request<{ deleted: boolean }>(`/documents/${id}`, { method: 'DELETE' }),
  // Todos
  listTodos: (includeCompleted = true, q = '') =>
    request<Todo[]>(`/todos?include_completed=${includeCompleted}&q=${encodeURIComponent(q)}`),

  checkTodoDuplicates: (title: string, dueDate?: string, excludeId?: string) =>
    request<Todo[]>(`/todos/check-duplicates?title=${encodeURIComponent(title)}${dueDate ? `&due_date=${encodeURIComponent(dueDate)}` : ''}${excludeId ? `&exclude_id=${excludeId}` : ''}`),

  createTodo: (data: TodoCreate) =>
    request<Todo>('/todos', { method: 'POST', body: JSON.stringify(data) }),

  updateTodo: (id: string, data: TodoUpdate) =>
    request<Todo>(`/todos/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteTodo: (id: string) =>
    request<{ deleted: boolean }>(`/todos/${id}`, { method: 'DELETE' }),

  // Events
  listEvents: (startDate = '', endDate = '', q = '') =>
    request<Event[]>(`/events?start_date=${startDate}&end_date=${endDate}&q=${encodeURIComponent(q)}`),

  checkEventDuplicates: (title: string, startTime: string, excludeId?: string) =>
    request<Event[]>(`/events/check-duplicates?title=${encodeURIComponent(title)}&start_time=${encodeURIComponent(startTime)}${excludeId ? `&exclude_id=${excludeId}` : ''}`),

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

  // Location
  getLocation: () =>
    request<{ lat: number | null; lon: number | null; city: string; country: string }>('/location'),

  setLocation: (data: { lat: number; lon: number; city?: string; country?: string }) =>
    request<{ status: string }>('/location', { method: 'POST', body: JSON.stringify(data) }),

  // Search
  searchAll: (q: string) =>
    request<SearchResults>(`/search?q=${encodeURIComponent(q)}&limit=20`),

  // Dashboard
  getDashboard: () =>
    request<DashboardData>('/dashboard'),

  getDashboardWeather: () =>
    request<DashboardWeather>('/dashboard/weather'),

  getAiNews: () =>
    request<AiNewsResponse>('/dashboard/ai-news'),

  // Voice
  getVoiceStatus: () =>
    request<{ enabled: boolean; stt: string; tts: string; note: string }>('/voice/status'),

  synthesizeSpeech: async (text: string): Promise<Blob> => {
    const res = await fetch(`${BASE}/voice/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })
    if (!res.ok) throw new Error(`TTS HTTP ${res.status}`)
    return res.blob()
  },
}
