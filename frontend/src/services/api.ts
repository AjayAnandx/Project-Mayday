import type { Todo, TodoCreate, TodoUpdate } from '../types/todo'
import type { Event, EventCreate, EventUpdate } from '../types/event'
import type { GraphData, GraphNode } from '../types/graph'
import type { SearchResults } from '../types/search'
import type { DashboardData, DashboardWeather, AiNewsResponse } from '../types/dashboard'
import type { DocumentMeta } from '../types/document'
import type { DataImportFile, DataImportParseResult, ChartOutput } from '../types/data-import'
import type { ResearchProject, ResearchDataPoint } from '../types/research'
import type { Project, ProjectDataPoint } from '../types/project'

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
  // Data Import
  uploadDataFile: async (file: File): Promise<{ file_id: string; filename: string; size: number }> => {
    const formData = new FormData()
    formData.append('file', file)
    const res = await fetch(`${BASE}/data/import`, {
      method: 'POST',
      body: formData,
    })
    if (!res.ok) {
      const err = await res.text()
      throw new Error(err || `HTTP ${res.status}`)
    }
    return res.json()
  },

  parseDataFile: async (fileId: string, sheetName?: string, headerRow = 0): Promise<DataImportParseResult> => {
    const formData = new FormData()
    formData.append('file_id', fileId)
    if (sheetName) formData.append('sheet_name', sheetName)
    formData.append('header_row', String(headerRow))
    const res = await fetch(`${BASE}/data/parse`, {
      method: 'POST',
      body: formData,
    })
    if (!res.ok) {
      const err = await res.text()
      throw new Error(err || `HTTP ${res.status}`)
    }
    return res.json()
  },

  importDataToStore: async (fileId: string, storeType: 'research' | 'project', options?: { sheetName?: string; headerRow?: number; topic?: string; projectName?: string }): Promise<{ message: string; data_points: number; detected: any }> => {
    const formData = new FormData()
    formData.append('file_id', fileId)
    formData.append('store_type', storeType)
    if (options?.sheetName) formData.append('sheet_name', options.sheetName)
    formData.append('header_row', String(options?.headerRow ?? 0))
    if (options?.topic) formData.append('topic', options.topic)
    if (options?.projectName) formData.append('project_name', options.projectName)
    const res = await fetch(`${BASE}/data/import-to-store`, {
      method: 'POST',
      body: formData,
    })
    if (!res.ok) {
      const err = await res.text()
      throw new Error(err || `HTTP ${res.status}`)
    }
    return res.json()
  },

  listDataFiles: () =>
    request<{ files: DataImportFile[] }>('/data/files'),
  // Research
  listResearch: (status = '', q = '') =>
    request<ResearchProject[]>(`/research?status=${encodeURIComponent(status)}&q=${encodeURIComponent(q)}`),

  getResearch: (topic: string) =>
    request<ResearchProject>(`/research/${encodeURIComponent(topic)}`),

  createResearch: (data: { topic: string; type: string; depth?: number; questions?: string[] }) =>
    request<ResearchProject>('/research', { method: 'POST', body: JSON.stringify(data) }),

  addResearchDataPoint: (data: { topic: string; label: string; value: string; unit?: string; confidence?: string; sources?: string[] }) =>
    request<ResearchDataPoint>('/research/data-points', { method: 'POST', body: JSON.stringify(data) }),

  generateResearchChart: (data: { topic: string; chart_type?: string; metric?: string }) =>
    request<{ chart_type: string; relative_url: string; data_points: number; url?: string; title?: string }>('/research/generate-chart', { method: 'POST', body: JSON.stringify(data) }),

  listResearchOutputs: (topic: string) =>
    request<ChartOutput[]>(`/research/${encodeURIComponent(topic)}/outputs`),

  // Projects
  listProjects: (status = '') =>
    request<Project[]>(`/projects?status=${encodeURIComponent(status)}`),

  getProject: (projectId: string) =>
    request<Project>(`/projects/${projectId}`),

  addProjectDataPoint: (projectId: string, data: { label: string; value: string; unit?: string; confidence?: string; sources?: string[] }) =>
    request<ProjectDataPoint>(`/projects/${projectId}/data-points`, { method: 'POST', body: JSON.stringify(data) }),

  generateProjectChart: (projectId: string, data: { chart_type?: string; metric?: string }) =>
    request<{ chart_type: string; relative_url: string; data_points: number; url?: string; title?: string }>(`/projects/${projectId}/generate-chart`, { method: 'POST', body: JSON.stringify(data) }),

  listProjectOutputs: (projectId: string) =>
    request<ChartOutput[]>(`/projects/${projectId}/outputs`),
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

}
