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
}

export interface TodoCreate {
  title: string
  description?: string
  due_date?: string | null
  priority?: number
  tags?: string[]
}

export interface TodoUpdate {
  title?: string
  description?: string
  due_date?: string | null
  priority?: number
  completed?: boolean
  tags?: string[]
}
