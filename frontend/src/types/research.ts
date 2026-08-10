export type ResearchStatus = 'active' | 'paused' | 'completed'

export type ResearchType =
  | 'market' | 'technical' | 'financial' | 'sales' | 'business'
  | 'academic' | 'competitive' | 'product' | 'domain' | 'person_org'
  | 'legal' | 'trend' | 'community'

export interface ResearchDataPoint {
  id: string
  label: string
  value: string
  unit?: string
  confidence?: string
  sources?: string[]
  created_at: string
}

export interface ResearchEntity {
  id: string
  name: string
  type: string
  description?: string
  relevance?: number
  sources?: string[]
  created_at: string
}

export interface ResearchFinding {
  id: string
  content: string
  confidence?: string
  sources?: string[]
  created_at: string
}

export interface ResearchTask {
  id: string
  title: string
  description?: string
  status: string
  depends_on?: string[]
  result?: string
  created_at: string
  updated_at: string
}

export interface ResearchProject {
  id: string
  topic: string
  slug: string
  type: ResearchType
  status: ResearchStatus
  depth: number
  summary?: string
  research_questions?: string[]
  data_points: ResearchDataPoint[]
  entities: ResearchEntity[]
  findings: ResearchFinding[]
  tasks: ResearchTask[]
  data_point_count?: number
  entity_count?: number
  finding_count?: number
  task_count?: number
  created_at: string
  updated_at: string
}

export interface ResearchSummary {
  id: string
  topic: string
  type: ResearchType
  status: ResearchStatus
  depth: number
  data_point_count: number
  entity_count: number
  finding_count: number
  task_count: number
  created_at: string
  updated_at: string
}

export interface ChartArtifact {
  url: string
  title: string
}
