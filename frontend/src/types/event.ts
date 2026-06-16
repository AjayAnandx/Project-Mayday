export interface Event {
  id: string
  title: string
  description: string
  start_time: string
  end_time: string
  all_day: boolean
  created_at: string
  updated_at: string
}

export interface EventCreate {
  title: string
  start_time: string
  end_time: string
  description?: string
  all_day?: boolean
}

export interface EventUpdate {
  title?: string
  start_time?: string
  end_time?: string
  description?: string
  all_day?: boolean
}
