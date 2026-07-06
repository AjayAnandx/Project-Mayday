import { useState, useRef, useCallback, useEffect } from 'react'
import { ChatWebSocket } from '../services/websocket'
import type { WsResponse } from '../types/chat'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  voice_content?: string
  tool_name?: string
  image_url?: string
}

export interface PendingSkill {
  name: string
  context: string
}

let msgId = 0
const nextId = () => `msg-${++msgId}`

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [connected, setConnected] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [toolCallCount, setToolCallCount] = useState(0)
  const [pendingSkill, setPendingSkill] = useState<PendingSkill | null>(null)
  const [activeSkill, setActiveSkill] = useState<string | null>(null)
  const wsRef = useRef<ChatWebSocket | null>(null)
  const currentAssistantId = useRef<string | null>(null)

  const addMessage = useCallback((msg: ChatMessage) => {
    setMessages((prev) => [...prev, msg])
  }, [])

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      addMessage({
        id: `reminder-${detail.id}`,
        role: 'assistant',
        content: `**${detail.title}** — ${detail.body}`,
      })
    }
    window.addEventListener('reminder-fired', handler)
    return () => window.removeEventListener('reminder-fired', handler)
  }, [addMessage])

  const appendToAssistant = useCallback((text: string, voiceContent?: string) => {
    setMessages((prev) => {
      const copy = [...prev]
      let last = copy[copy.length - 1]
      if (last && last.role === 'assistant') {
        copy[copy.length - 1] = { ...last, content: last.content + text, voice_content: voiceContent ?? last.voice_content }
      } else {
        const newId = nextId()
        currentAssistantId.current = newId
        copy.push({ id: newId, role: 'assistant', content: text, voice_content: voiceContent })
      }
      return copy
    })
  }, [])

  useEffect(() => {
    const ws = new ChatWebSocket('/ws/chat', {
      onMessage: (data: WsResponse) => {
        switch (data.type) {
          case 'token':
            setStreaming(true)
            appendToAssistant(data.content || '', data.voice_content)
            break
          case 'tool_call':
            addMessage({
              id: nextId(),
              role: 'tool',
              content: data.result || '',
              tool_name: data.name,
              image_url: data.image_url,
            })
            setToolCallCount((c) => c + 1)
            break
          case 'done':
            setStreaming(false)
            currentAssistantId.current = null
            break
          case 'error':
            addMessage({ id: nextId(), role: 'assistant', content: `Error: ${data.content}` })
            setStreaming(false)
            break
          case 'skill_suggested':
            setPendingSkill({ name: data.name || '', context: data.content || '' })
            break
          case 'skill_activated':
            setPendingSkill(null)
            setActiveSkill(data.name || '')
            break
          case 'skill_deactivated':
            setActiveSkill(null)
            break
          case 'conversation_loaded':
            if (data.conversation) {
              const msgs = data.conversation.messages.map((m) => ({
                id: nextId(),
                role: m.role as 'user' | 'assistant',
                content: m.content,
              }))
              setMessages(msgs)
            }
            break
        }
      },
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
    })
    ws.connect()
    wsRef.current = ws
    return () => {
      ws.disconnect()
    }
  }, [addMessage, appendToAssistant])

  const sendMessage = useCallback(
    (text: string) => {
      if (!text.trim() || !wsRef.current) return
      addMessage({ id: nextId(), role: 'user', content: text })
      wsRef.current.send({ type: 'message', content: text })
    },
    [addMessage],
  )

  const newConversation = useCallback(() => {
    setMessages([])
    setPendingSkill(null)
    setActiveSkill(null)
    wsRef.current?.send({ type: 'new_conversation' })
  }, [])

  const confirmSkill = useCallback((name: string) => {
    setPendingSkill(null)
    wsRef.current?.sendConfirmSkill(name)
  }, [])

  const dismissSkill = useCallback(() => {
    setPendingSkill(null)
    wsRef.current?.sendDismissSkill()
  }, [])

  return {
    messages,
    connected,
    streaming,
    sendMessage,
    newConversation,
    toolCallCount,
    pendingSkill,
    activeSkill,
    confirmSkill,
    dismissSkill,
  }
}
