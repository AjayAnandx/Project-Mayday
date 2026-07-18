import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, FileText, Upload } from 'lucide-react'
import { useChatContext } from '../../context/ChatContext'
import { MessageBubble } from './MessageBubble'
import { SkillSuggestionCard } from './SkillSuggestionCard'
import { useAutoResizeTextarea } from '../../hooks/use-auto-resize-textarea'
import { api } from '../../services/api'
import { cn } from '../../lib/utils'

export function ChatPanel() {
  const { messages, connected, streaming, sendMessage, pendingSkill, activeSkill, confirmSkill, dismissSkill, addSystemMessage } = useChatContext()
  const [input, setInput] = useState('')
  const [isFocused, setIsFocused] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const { textareaRef, adjustHeight } = useAutoResizeTextarea({ minHeight: 52, maxHeight: 200 })
  const dragCountRef = useRef(0)

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    dragCountRef.current++
    if (e.dataTransfer.types?.includes('Files')) {
      setDragOver(true)
    }
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    dragCountRef.current--
    if (dragCountRef.current <= 0) {
      dragCountRef.current = 0
      setDragOver(false)
    }
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
  }, [])

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    dragCountRef.current = 0
    const file = e.dataTransfer.files[0]
    if (!file || !file.name.toLowerCase().endsWith('.pdf')) {
      addSystemMessage('Only PDF files are supported for upload.')
      return
    }
    setUploading(true)
    try {
      const result = await api.uploadDocument(file)
      sendMessage(`I've uploaded a document: **${result.filename}** (${result.pages} pages, id: \`${result.id}\`). Please read it and understand its contents so you can answer questions about it.`)
    } catch (err: any) {
      addSystemMessage(`Upload failed: ${err.message || 'Unknown error'}`)
    } finally {
      setUploading(false)
    }
  }, [addSystemMessage, sendMessage])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pendingSkill])

  const handleSubmit = () => {
    if (!input.trim() || streaming) return
    sendMessage(input.trim())
    setInput('')
    adjustHeight(true)
  }

  return (
    <div
      className="flex flex-col h-full bg-crust relative"
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {dragOver && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-crust/80 backdrop-blur-sm rounded-2xl border-2 border-dashed border-green/50 m-2">
          <div className="flex flex-col items-center gap-3 text-green">
            <Upload className="h-10 w-10" />
            <p className="text-sm font-medium">{uploading ? 'Uploading...' : 'Drop PDF here to upload'}</p>
          </div>
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-3 sm:p-4 space-y-1">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-overlay0">
            <p className="text-xl sm:text-2xl font-bold bg-gradient-to-r from-green to-green/60 bg-clip-text text-transparent mb-2">Mayday</p>
            <p className="text-xs sm:text-sm text-overlay0 px-4 sm:px-0 text-center">Ask me to create todos, events, or anything else!</p>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {pendingSkill && (
          <SkillSuggestionCard
            name={pendingSkill.name}
            context={pendingSkill.context}
            onConfirm={() => confirmSkill(pendingSkill.name)}
            onDismiss={dismissSkill}
          />
        )}
        {streaming && (
          <div className="flex justify-start my-1">
            <div className="bg-surface0/50 rounded-lg px-4 py-2.5">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="px-3 sm:px-4 pb-3 sm:pb-4 pt-2">
        <div className="mx-auto w-full max-w-2xl">
          {activeSkill && !pendingSkill && (
            <div className="mb-2 flex items-center gap-2 rounded-full bg-green/10 border border-green/20 px-4 py-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-green animate-pulse" />
              <span className="text-xs text-green font-medium">Active skill: {activeSkill}</span>
            </div>
          )}
          <div
            className={cn(
              'relative flex w-full cursor-text items-end rounded-xl transition-all duration-200 outline-none overflow-hidden',
              'bg-black/60 ring-1 ring-white/10',
              isFocused && 'ring-green/50 shadow-lg shadow-green/10',
            )}
            onClick={() => textareaRef.current?.focus()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') textareaRef.current?.focus()
            }}
            role="textbox"
            tabIndex={0}
          >
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value)
                adjustHeight()
              }}
              onFocus={() => setIsFocused(true)}
              onBlur={() => setIsFocused(false)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSubmit()
                }
              }}
              placeholder={connected ? 'Type a message...' : 'Connecting...'}
              disabled={!connected || streaming}
              className="flex-1 resize-none bg-transparent px-4 sm:px-5 py-3 sm:py-3.5 pr-14 text-sm text-text placeholder-overlay0 outline-none border-none leading-snug"
              rows={1}
            />

            <div className="absolute right-1.5 bottom-1.5 flex items-center gap-0.5">
              <input
                type="file"
                accept=".pdf"
                id="pdf-upload"
                className="hidden"
                onChange={async (e) => {
                  const file = e.target.files?.[0]
                  if (!file) return
                  setUploading(true)
                  try {
                    const result = await api.uploadDocument(file)
                    sendMessage(`I've uploaded a document: **${result.filename}** (${result.pages} pages, id: \`${result.id}\`). Please read it and understand its contents so you can answer questions about it.`)
                  } catch (err: any) {
                    addSystemMessage(`Upload failed: ${err.message || 'Unknown error'}`)
                  } finally {
                    setUploading(false)
                    e.target.value = ''
                  }
                }}
              />
              <label
                htmlFor="pdf-upload"
                className={cn(
                  'rounded-full p-2.5 transition-all cursor-pointer',
                  'text-overlay0 hover:text-text hover:bg-surface1/50',
                  uploading && 'opacity-50 pointer-events-none',
                )}
                title="Upload PDF"
              >
                <FileText className="h-4 w-4" />
              </label>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!input.trim() || !connected || streaming}
                className={cn(
                  'rounded-full p-2.5 transition-all',
                  input.trim() && !streaming
                    ? 'bg-green/15 text-green hover:bg-green/25'
                    : 'text-overlay0 hover:text-text hover:bg-surface1/50',
                )}
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
