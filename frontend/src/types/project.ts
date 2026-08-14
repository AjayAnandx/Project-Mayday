export type ProjectStatus = 'active' | 'paused' | 'scrapped'

export interface ProjectDataPoint {
  id: string
  label: string
  value: string
  unit?: string
  confidence?: string
  sources?: string[]
  created_at: string
}

export interface ProjectTask {
  id: string
  title: string
  description?: string
  status: string
  depends_on?: string[]
  result?: string
  created_at: string
  updated_at: string
}

export interface Project {
  id: string
  name: string
  slug: string
  status: ProjectStatus
  description?: string
  data_points: ProjectDataPoint[]
  tasks: ProjectTask[]
  data_point_count?: number
  task_count?: number
  created_at: string
  updated_at: string
}

export interface ProjectSummary {
  id: string
  name: string
  slug: string
  status: ProjectStatus
  description?: string
  data_point_count: number
  task_count: number
  created_at: string
  updated_at: string
}

export interface ChartArtifact {
  url: string
  title: string
}