export interface RecurrenceRule {
  pattern: 'daily' | 'weekly' | 'biweekly' | 'monthly' | 'yearly'
  interval?: number
  end_date?: string
  count?: number
}

export interface Todo {
  id: string
  title: string
  description: string
  due_date: string | null
  priority: number
  completed: boolean
  tags: string[]
  created_at: string
  updated_at: string
  recurrence?: RecurrenceRule
}

export interface TodoCreate {
  title: string
  description?: string
  due_date?: string | null
  priority?: number
  tags?: string[]
  recurrence?: RecurrenceRule
}

export interface TodoUpdate {
  title?: string
  description?: string
  due_date?: string | null
  priority?: number
  completed?: boolean
  tags?: string[]
  recurrence?: RecurrenceRule
}
