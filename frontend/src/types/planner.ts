export type ItemKind = 'task' | 'event' | 'reminder' | 'waiting'
export type ItemStatus = 'open' | 'done' | 'cancelled'
export type PlannerView = 'inbox' | 'today' | 'upcoming' | 'waiting' | 'done' | 'all' | 'calendar'

export interface PlanRecurrence {
  freq: 'daily' | 'weekly' | 'monthly' | 'yearly'
  interval?: number
  /** 0 = Monday … 6 = Sunday */
  byweekday?: number[]
  bymonthday?: number
  until?: string
  count?: number
  repeat_from?: 'due' | 'completion'
}

export interface PlanReminder {
  id?: string
  /** absolute local time */
  at?: string
  /** minutes before the due/start time */
  offset_min?: number
}

export interface ChecklistEntry {
  id?: string
  text: string
  done: boolean
}

export interface ChaseEntry {
  at: string
  channel: string
  note: string
  draft_id: string
}

/** Times are local wall-clock strings: 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM'. */
export interface PlannerItem {
  id: string
  kind: ItemKind
  title: string
  notes: string
  status: ItemStatus
  completed_at: string | null
  list: string
  tags: string[]
  /** 1 high · 2 medium · 3 low · 4 none */
  priority: number
  start_at: string | null
  due_at: string | null
  end_at: string | null
  all_day: boolean
  deadline: string | null
  estimate_min: number | null
  scheduled_block: { start: string; end: string } | null
  /** null = defaults for the kind, [] = no alerts */
  reminders: PlanReminder[] | null
  recurrence: PlanRecurrence | null
  completions: { at: string; due: string }[]
  parent_id: string | null
  checklist: ChecklistEntry[]
  person_id: string | null
  follow_up_at: string | null
  chase_log: ChaseEntry[]
  snoozed_until: string | null
  source: { type: string }
  created_at: string
  updated_at: string
  /** present on calendar/upcoming instances */
  occurrence_at?: string
  _instance?: boolean
  _rolled_to?: string
}

export type PlannerItemInput = Partial<Omit<PlannerItem, 'id' | 'created_at' | 'updated_at'>> & { title?: string }

export interface Person {
  id: string
  name: string
  email: string
  phone: string
  relation: string
  notes: string
  waiting_count?: number
  owed_count?: number
}

export interface PersonDetail extends Person {
  they_owe: PlannerItem[]
  i_owe: PlannerItem[]
  events: PlannerItem[]
}

export interface PlannerSummary {
  counts: { inbox: number; today: number; upcoming: number; waiting: number; overdue: number }
  lists: { name: string; open: number }[]
  tags: string[]
}

export interface QuickAddParse {
  title: string
  kind: ItemKind
  due_at?: string
  start_at?: string
  end_at?: string
  person?: string
  tags?: string[]
  list?: string
  priority?: number
  recurrence?: PlanRecurrence
  estimate_min?: number
}

export interface DayPlan {
  date: string
  blocks: { item_id: string; title: string; start: string; end: string }[]
  unplaced: { item_id: string; title: string }[]
  summary: string
}

export interface NudgeResult {
  drafted: boolean
  draft_id?: string
  reason?: string
  subject?: string
  body?: string
  to?: string
}

export interface DigestPreview {
  subject: string
  text: string
  html: string
  sections: [string, string[]][]
  to: string
  enabled: boolean
  morning: string
  evening: string
}
