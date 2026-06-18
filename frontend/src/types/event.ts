import type { RecurrenceRule } from './todo'

export type { RecurrenceRule }

export interface Event {
  id: string
  title: string
  description: string
  start_time: string
  end_time: string
  all_day: boolean
  created_at: string
  updated_at: string
  recurrence?: RecurrenceRule
}

export interface EventCreate {
  title: string
  start_time: string
  end_time: string
  description?: string
  all_day?: boolean
  recurrence?: RecurrenceRule
}

export interface EventUpdate {
  title?: string
  start_time?: string
  end_time?: string
  description?: string
  all_day?: boolean
  recurrence?: RecurrenceRule
}
