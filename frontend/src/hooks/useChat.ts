import { useState, useRef, useCallback, useEffect } from 'react'
import { ChatWebSocket } from '../services/websocket'
import type { WsResponse } from '../types/chat'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  tool_name?: string
}

let msgId = 0
const nextId = () => `msg-${++msgId}`

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [connected, setConnected] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const wsRef = useRef<ChatWebSocket | null>(null)
  const currentAssistantId = useRef<string | null>(null)

  const addMessage = useCallback((msg: ChatMessage) => {
    setMessages((prev) => [...prev, msg])
  }, [])

  const appendToAssistant = useCallback((text: string) => {
    setMessages((prev) => {
      const copy = [...prev]
      let last = copy[copy.length - 1]
      if (last && last.role === 'assistant') {
        copy[copy.length - 1] = { ...last, content: last.content + text }
      } else {
        // Create a new assistant message
        const newId = nextId()
        currentAssistantId.current = newId
        copy.push({ id: newId, role: 'assistant', content: text })
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
            appendToAssistant(data.content || '')
            break
          case 'tool_call':
            addMessage({
              id: nextId(),
              role: 'tool',
              content: data.result || '',
              tool_name: data.name,
            })
            break
          case 'done':
            setStreaming(false)
            currentAssistantId.current = null
            break
          case 'error':
            addMessage({ id: nextId(), role: 'assistant', content: `Error: ${data.content}` })
            setStreaming(false)
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
    wsRef.current?.send({ type: 'new_conversation' })
  }, [])

  return {
    messages,
    connected,
    streaming,
    sendMessage,
    newConversation,
  }
}
