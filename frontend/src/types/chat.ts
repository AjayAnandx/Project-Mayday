/** Inline OpenUI spec built by backend/core/openui_builder.py. */
export interface UiPayload {
  lang: string
  title?: string
  fallback_text?: string
}

export interface WsMessage {
  type: 'message' | 'new_conversation' | 'load_conversation' | 'confirm_skill' | 'dismiss_skill' | 'music_command' | 'confirm_phase'
  phase?: string
  content?: string
  conversation_id?: string
  name?: string
  context?: string
  action?: string
  video_id?: string
  videoId?: string
  title?: string
  artist?: string
  thumb?: string
  thumbnail?: string
  language?: string
}

export interface MusicWsResponse {
  type: 'music'
  action: string
  track: import('./music').MusicTrack
  queue: import('./music').MusicTrack[]
}

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
  messages: { role: string; content: string; timestamp: string }[]
}

export interface WsResponse {
  type: 'token' | 'tool_call' | 'done' | 'error' | 'conversation_loaded' | 'skill_suggested' | 'skill_activated' | 'skill_deactivated' | 'music' | 'approval_gate'
  ui?: UiPayload
  phase?: string
  message?: string
  content?: string
  voice_content?: string
  name?: string
  result?: string
  image_url?: string
  artifact_url?: string
  artifact_title?: string
  open_in_new_tab?: boolean
  conversation?: Conversation
  action?: string
  track?: import('./music').MusicTrack
  queue?: import('./music').MusicTrack[]
}
