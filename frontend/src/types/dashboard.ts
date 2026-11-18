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
  analytics?: DashboardAnalytics | null
}

export interface DashboardAnalytics {
  daily: { date: string; count: number }[]
  total: number
  prev_total: number
  /** [4-hour bucket 0..5][weekday Sun..Sat] */
  heatmap: number[][]
  day_parts: { morning: number; afternoon: number; evening: number }
  by_entity: Record<string, number>
  todos: { total: number; completed: number; overdue: number }
  mix?: { recent: ActivityMixData; all: ActivityMixData }
}

export type MixGroupKey = 'email' | 'research' | 'projects' | 'tasks' | 'calendar' | 'memory'

export interface ActivityMixData {
  total: number
  /** bucket labels for each group's series: days (recent) or YYYY-MM (all) */
  buckets: string[]
  groups: { key: MixGroupKey; count: number; daily: number[] }[]
  actions: { created: number; updated: number; removed: number }
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
