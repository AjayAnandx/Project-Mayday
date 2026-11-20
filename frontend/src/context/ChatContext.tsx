import { createContext, useContext, useEffect, ReactNode } from 'react'
import { useChat, ChatMessage, PendingSkill } from '../hooks/useChat'
import type { WsResponse } from '../types/chat'

interface ChatContextValue {
  messages: ChatMessage[]
  connected: boolean
  streaming: boolean
  sendMessage: (text: string) => void
  confirmPhase: (phase: string) => void
  newConversation: () => void
  toolCallCount: number
  pendingSkill: PendingSkill | null
  activeSkill: string | null
  confirmSkill: (name: string) => void
  dismissSkill: () => void
  addSystemMessage: (content: string) => void
  sendMusicCommand: (payload: { action: string; video_id?: string; title?: string; artist?: string; thumb?: string; language?: string }) => void
  ingestEvent: (data: WsResponse) => void
  addUserMessage: (text: string) => void
}

const ChatContext = createContext<ChatContextValue | null>(null)

export function ChatProvider({ children }: { children: ReactNode }) {
  const chat = useChat()
  const { sendMessage } = chat
  // Brain V3 P14: a suggestion's "Do it" can hand a request to chat (e.g. "run my usual routine")
  useEffect(() => {
    const onSend = (e: Event) => {
      const text = (e as CustomEvent<string>).detail
      if (typeof text === 'string' && text.trim()) sendMessage(text)
    }
    window.addEventListener('mayday-chat-send', onSend)
    return () => window.removeEventListener('mayday-chat-send', onSend)
  }, [sendMessage])
  return <ChatContext.Provider value={chat}>{children}</ChatContext.Provider>
}

export function useChatContext() {
  const ctx = useContext(ChatContext)
  if (!ctx) throw new Error('useChatContext must be used within ChatProvider')
  return ctx
}
