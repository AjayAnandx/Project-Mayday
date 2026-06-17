export interface WsMessage {
  type: 'message' | 'new_conversation' | 'load_conversation'
  content?: string
  conversation_id?: string
}

export interface WsResponse {
  type: 'token' | 'tool_call' | 'done' | 'error' | 'conversation_loaded'
  content?: string
  name?: string
  result?: string
  image_url?: string
  conversation?: import('./conversation').Conversation
}
