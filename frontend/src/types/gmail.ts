export interface GmailStatus {
  enabled: boolean
  account: string
  agent_email: string
  authenticated: boolean
  history_id: string | null
  redirect_uri: string
  ui_mode: string
}

export interface GmailMessages {
  q: string
  messages: { id: string; threadId: string }[]
  resultSizeEstimate: number
}
