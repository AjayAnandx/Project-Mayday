import type { Todo } from './todo'
import type { Event } from './event'

export interface DashboardStats {
  open_todos: number
  overdue_todos: number
  today_events: number
  upcoming_events_count: number
  total_conversations: number
  active_projects: number
  graph_nodes: number
}

export interface DashboardOperation {
  id: string
  timestamp: string
  action: string
  entity_type: string
  entity_name: string
  details?: Record<string, unknown>
}

export interface DashboardMusic {
  total_plays: number
  language_stats: Record<string, number>
  top_week: { video_id: string; title: string; artist: string; language: string; thumb: string; plays: number; last_played: string }[]
  top_all: { video_id: string; title: string; artist: string; language: string; thumb: string; plays: number; last_played: string }[]
}

export interface DashboardData {
  stats: DashboardStats
  upcoming_events: Event[]
  open_todos: Todo[]
  overdue_todos: Todo[]
  recent_activity: DashboardOperation[]
  music?: DashboardMusic
}

export interface AiNewsArticle {
  title: string
  url: string
  published_date: string
  summary: string
}

export interface AiNewsResponse {
  articles: AiNewsArticle[]
  cached_at: string
  error?: string
}

export interface DashboardWeather {
  available: boolean
  location?: string
  raw?: string
  message?: string
}
