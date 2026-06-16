export interface Message {
  role: string
  content: string
  timestamp: string
}

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
  messages: Message[]
}
