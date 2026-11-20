import { useState, useRef, useCallback, useEffect } from 'react'
import { ChatWebSocket } from '../services/websocket'
import type { UiPayload, WsResponse } from '../types/chat'
import { markAssistantDone, markUserSend, wireVisibility } from '../services/brainSignals'

wireVisibility()

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  voice_content?: string
  tool_name?: string
  image_url?: string
  artifact_url?: string
  artifact_title?: string
  open_in_new_tab?: boolean
  ui?: UiPayload
}

export interface PendingSkill {
  name: string
  context: string
}

let msgId = 0
const nextId = () => `msg-${++msgId}`

/** Stored message → chat message. Tool results that carried an inline OpenUI card keep it. */
function restoreMessage(m: { role: string; content: string }): ChatMessage {
  const base: ChatMessage = { id: nextId(), role: m.role as ChatMessage['role'], content: m.content }
  if (m.role !== 'tool' || !m.content?.includes('"ui"')) return base
  try {
    const data = JSON.parse(m.content)
    if (data && typeof data.ui?.lang === 'string') {
      return { ...base, content: data.message || data.ui.fallback_text || '', ui: data.ui, tool_name: 'tool' }
    }
  } catch { /* plain text tool result */ }
  return base
}

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

  // Shared server-message handler: used by /ws/chat AND by realtime worker
  // progress events forwarded over the realtime socket (ingestEvent).
  const handleServerMessage = useCallback((data: WsResponse) => {
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
          artifact_url: data.artifact_url,
          artifact_title: data.artifact_title,
          open_in_new_tab: data.open_in_new_tab,
          ui: data.ui,
        })
        setToolCallCount((c) => c + 1)
        // A tool with an inline OpenUI card shows it in the chat; its page artifact (if any)
        // stays available from the card instead of auto-opening.
        if (data.artifact_url && !data.ui) {
          window.dispatchEvent(new CustomEvent('open-artifact', {
            detail: { url: data.artifact_url, title: data.artifact_title || 'Artifact' },
          }))
        }
        if (data.open_in_new_tab && data.artifact_url && !data.ui) {
          window.open(data.artifact_url, '_blank')
        }
        break
      case 'done':
        setStreaming(false)
        currentAssistantId.current = null
        markAssistantDone()
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
      case 'approval_gate': {
        // The backend can announce the same pause twice (socket + engine); keep one card per
        // pending phase. "Approved" notices (no ui) clear the card.
        const msg: ChatMessage = { id: nextId(), role: 'tool', tool_name: 'approval', content: data.message || '', ui: data.ui }
        setMessages(prev => {
          const last = prev[prev.length - 1]
          const lastIsApproval = last?.role === 'tool' && last.tool_name === 'approval' && !!last.ui
          if (!data.ui) return lastIsApproval ? prev.slice(0, -1) : prev
          return lastIsApproval ? [...prev.slice(0, -1), msg] : [...prev, msg]
        })
        break
      }
      case 'conversation_loaded':
        if (data.conversation) {
          const msgs = data.conversation.messages.map((m) => restoreMessage(m))
          setMessages(msgs)
        }
        break
      case 'music':
        window.dispatchEvent(new CustomEvent('mayday-music', { detail: data }))
        break
    }
  }, [addMessage, appendToAssistant])

  // Ingest engine events arriving over another socket (realtime worker progress).
  const ingestEvent = useCallback((data: WsResponse) => {
    handleServerMessage(data)
  }, [handleServerMessage])

  const addUserMessage = useCallback((text: string) => {
    if (!text.trim()) return
    addMessage({ id: nextId(), role: 'user', content: text })
  }, [addMessage])

  useEffect(() => {
    const ws = new ChatWebSocket('/ws/chat', {
      onMessage: (data: WsResponse) => handleServerMessage(data),
      onOpen: () => {
        setConnected(true)
        setStreaming(false)
        currentAssistantId.current = null
      },
      onClose: () => setConnected(false),
    })
    ws.connect()
    wsRef.current = ws
    return () => {
      ws.disconnect()
    }
  }, [handleServerMessage])

  const sendMessage = useCallback(
    (text: string) => {
      if (!text.trim() || !wsRef.current) return
      addMessage({ id: nextId(), role: 'user', content: text })
      markUserSend(text.length)
      wsRef.current.send({ type: 'message', content: text })
    },
    [addMessage],
  )

  const newConversation = useCallback(() => {
    setMessages([])
    setStreaming(false)
    setPendingSkill(null)
    setActiveSkill(null)
    currentAssistantId.current = null
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

  const addSystemMessage = useCallback((content: string) => {
    addMessage({ id: nextId(), role: 'assistant', content })
  }, [addMessage])

  const confirmPhase = useCallback((phase: string) => {
    wsRef.current?.sendConfirmPhase(phase)
  }, [])

  const sendMusicCommand = useCallback((payload: { action: string; video_id?: string; title?: string; artist?: string; thumb?: string; language?: string }) => {
    wsRef.current?.sendMusicCommand(payload)
  }, [])

  return {
    messages,
    connected,
    streaming,
    sendMessage,
    confirmPhase,
    newConversation,
    toolCallCount,
    pendingSkill,
    activeSkill,
    confirmSkill,
    dismissSkill,
    addSystemMessage,
    sendMusicCommand,
    ingestEvent,
    addUserMessage,
  }
}
