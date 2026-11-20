// Evidence-based research runs (backend/core/research_flow.py, /api/research/{topic}/runs…)

export type RunStatus = 'running' | 'completed' | 'stopped' | 'failed'
export type ClaimStatus = 'supported' | 'contested' | 'unsupported' | 'unverified'
export type SourceTier = 'primary' | 'secondary' | 'tertiary' | 'unknown'
export type Preset = 'quick' | 'standard' | 'deep'
export type EvidenceStatus = 'peer_reviewed' | 'preprint' | 'retracted' | 'unknown'
export type EvidenceLevel = 'strong' | 'moderate' | 'limited' | 'weak' | 'retracted'
export type Field = 'general' | 'cs_ml' | 'social_science'

/** Scholarly metadata on a source (backend/core/scholarly.py). */
export interface ScholarlyFields {
  evidence_status?: EvidenceStatus | null
  is_retracted?: boolean
  is_oa?: boolean
  oa_pdf_url?: string | null
  authors?: string[]
  venue?: string
  year?: number | string | null
  doi?: string | null
  arxiv_id?: string | null
}

export interface Study {
  design?: string
  sample_n?: string
  population?: string
  intervention?: string
  comparator?: string
  dataset?: string
  outcome?: string
  effect?: { metric?: string; value?: string; ci?: string }
  p_value?: string
  limitations?: string
  dropped_unquoted?: string[]
}

export interface Hypothesis {
  id: string
  label: string
  statement: string
  verdict?: 'supported' | 'refuted' | 'inconclusive' | 'untested'
  support?: number
  refute?: number
  claims?: { claim_id: string; stance: string; weight: number; level: string | null; statement: string }[]
}

export const RUN_STAGES = ['scope', 'plan', 'gather', 'extract', 'verify', 'synthesize', 'review', 'deliver'] as const

export interface RunUsage { sources: number; llm_calls: number; cost_usd: number }
export interface RunBudget { max_minutes: number; max_sources: number; max_cost_usd: number }

export interface RunSummary {
  id: string
  status: RunStatus
  stage: string
  usage: RunUsage
  budget: RunBudget
  error: string | null
  started_at: string
  finished_at: string | null
  outputs: string[]
  questions: string[]
  answered: number
}

export interface StageEntry { stage: string; passed: boolean; notes: string; at: string }

export interface RunAnswer {
  question: string
  answer: string
  rendered: string            // [n] markers resolve to cited_sources[n-1]
  claim_ids: string[]
  dropped_sentences: number
}

export interface CitedSource extends ScholarlyFields {
  n: number
  id: string
  title: string
  url: string
  type: string
  tier: SourceTier
  published_date: string
  access: string | null
}

export interface RunDetail extends Omit<RunSummary, 'questions' | 'answered'> {
  brief: { request?: string; questions: string[]; scope?: string; field?: Field
           criteria?: { include?: string[]; exclude?: string[] } }
  hypotheses?: Hypothesis[]
  selection?: Record<string, number | string[]>
  search_log?: { query: string; kind: string; results: number; at: string }[]
  stages: StageEntry[]
  answers: RunAnswer[]
  gaps?: string[]
  review?: string[]
  cited_sources: CitedSource[]
  models: Record<string, string>
}

export interface Claim {
  id: string
  statement: string
  status: ClaimStatus
  confidence: number
  confidence_reasons: string[]
  kind: string
  value: string | null
  unit: string
  as_of: string
  question: string
  run_id: string | null
  quote: string
  verified: boolean | null
  study?: Study | null
  evidence_level?: EvidenceLevel | null
  hypothesis_id?: string | null
  hypothesis_stance?: string | null
  source: { id: string | null; title: string | null; url: string | null; tier: SourceTier | null
            evidence_status?: EvidenceStatus | null }
}

export interface Source extends ScholarlyFields {
  id: string
  title: string
  url: string
  type: string
  tier: SourceTier
  publisher: string
  published_date: string
  access: string | null
  fetched_at: string | null
  content_hash: string | null
  verified_claims: number
}

export interface TopicSummary {
  id: string
  topic: string
  type: string
  status: string
  updated_at: string
}
