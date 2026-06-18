export interface SearchTodoResult {
  id: string
  title: string
  snippet: string
}

export interface SearchEventResult {
  id: string
  title: string
  snippet: string
}

export interface SearchConversationResult {
  id: string
  title: string
  date: string
  snippet: string
}

export interface SearchGraphResult {
  id: string
  label: string
  type: string
  snippet: string
}

export interface SearchOperationResult {
  id: string
  action: string
  entity_type: string
  entity_name: string
  timestamp: string
}

export interface SearchResults {
  todos: SearchTodoResult[]
  events: SearchEventResult[]
  conversations: SearchConversationResult[]
  graph_nodes: SearchGraphResult[]
  operations: SearchOperationResult[]
}
