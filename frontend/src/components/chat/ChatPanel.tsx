import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import {
  ArrowUp, CalendarCheck, FileText, Hourglass, Inbox, Mic, Plus, Sparkles, Sun, Upload,
} from 'lucide-react'
import { useChatContext } from '../../context/ChatContext'
import type { ChatMessage } from '../../hooks/useChat'
import { MaydayAvatar, MessageBubble, ToolActivity } from './MessageBubble'
import { SkillSuggestionCard } from './SkillSuggestionCard'
import { useAutoResizeTextarea } from '../../hooks/use-auto-resize-textarea'
import { usePlannerVersion } from '../../hooks/usePlanner'
import { api } from '../../services/api'
import { cn } from '../../lib/utils'
import type { PlannerSummary } from '../../types/planner'

const SUGGESTIONS = [
  { icon: Sun, title: 'Plan my day', prompt: 'Plan my day — fit my open tasks around today\'s meetings.' },
  { icon: CalendarCheck, title: "What's on tomorrow?", prompt: 'What do I have tomorrow? Include tasks and events.' },
  { icon: Hourglass, title: 'Who owes me what?', prompt: 'Who is waiting on what, and who should I follow up with?' },
  { icon: Inbox, title: 'Catch me up on email', prompt: 'Summarize my unread email and pull out anything I need to act on.' },
]

type Block = { kind: 'msg'; msg: ChatMessage } | { kind: 'tools'; tools: ChatMessage[] }

/** Merge consecutive tool messages into one collapsible activity card. */
function toBlocks(messages: ChatMessage[]): Block[] {
  const out: Block[] = []
  for (const m of messages) {
    const last = out[out.length - 1]
    if (m.role === 'tool') {
      if (last?.kind === 'tools') last.tools.push(m)
      else out.push({ kind: 'tools', tools: [m] })
    } else if (!(m.role === 'assistant' && !m.content)) {
      out.push({ kind: 'msg', msg: m })
    }
  }
  return out
}

function greeting() {
  const h = new Date().getHours()
  return h < 5 ? 'Working late' : h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

export function ChatPanel() {
  const {
    messages, connected, streaming, sendMessage, newConversation,
    pendingSkill, activeSkill, confirmSkill, dismissSkill, addSystemMessage,
  } = useChatContext()
  const [input, setInput] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [summary, setSummary] = useState<PlannerSummary | null>(null)
  const plannerVersion = usePlannerVersion()
  const bottomRef = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const { textareaRef, adjustHeight } = useAutoResizeTextarea({ minHeight: 46, maxHeight: 220 })
  const dragCountRef = useRef(0)
  const blocks = useMemo(() => toBlocks(messages), [messages])
  const empty = blocks.length === 0
  // show "thinking" from the moment a message is sent, not only once tokens stream
  const lastBlock = blocks[blocks.length - 1]
  const awaiting = streaming || (lastBlock?.kind === 'msg' && lastBlock.msg.role === 'user')

  useEffect(() => {
    if (!empty) return
    api.planner.summary().then(setSummary).catch(() => setSummary(null))
  }, [empty, plannerVersion])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pendingSkill, awaiting])

  const uploadPdf = useCallback(async (file: File | undefined) => {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.pdf')) {
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

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    dragCountRef.current++
    if (e.dataTransfer.types?.includes('Files')) setDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    dragCountRef.current--
    if (dragCountRef.current <= 0) {
      dragCountRef.current = 0
      setDragOver(false)
    }
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    dragCountRef.current = 0
    uploadPdf(e.dataTransfer.files[0])
  }, [uploadPdf])

  const submit = (text = input) => {
    if (!text.trim() || streaming || !connected) return
    sendMessage(text.trim())
    setInput('')
    adjustHeight(true)
  }

  const canSend = !!input.trim() && connected && !streaming

  return (
    <div
      className="flex flex-col h-full bg-crust relative"
      onDragEnter={handleDragEnter}
      onDragOver={e => e.preventDefault()}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {dragOver && (
        <div className="absolute inset-3 z-50 flex items-center justify-center rounded-[24px] border-2 border-dashed border-green/50 bg-crust/85 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-3 text-green">
            <Upload className="h-10 w-10" />
            <p className="text-sm font-medium">{uploading ? 'Uploading…' : 'Drop a PDF to share it with Mayday'}</p>
          </div>
        </div>
      )}

      {/* page bar */}
      <div className="shrink-0 px-4 sm:px-6 pt-4">
        <div className="max-w-3xl mx-auto flex items-center gap-2">
          <span className={cn('flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px]',
            connected ? 'border-green/25 text-green bg-green/[0.06]' : 'border-yellow/30 text-yellow bg-yellow/[0.06]')}>
            <span className={cn('w-1.5 h-1.5 rounded-full', connected ? 'bg-green' : 'bg-yellow animate-pulse')} />
            {connected ? 'Connected' : 'Reconnecting…'}
          </span>
          {activeSkill && !pendingSkill && (
            <span className="flex items-center gap-1.5 rounded-full border border-white/10 px-2.5 py-1 text-[11px] text-subtext1">
              <Sparkles className="h-3 w-3 text-green" /> Skill: {activeSkill}
            </span>
          )}
          <span className="flex-1" />
          {!empty && (
            <button onClick={newConversation}
                    className="flex items-center gap-1.5 rounded-xl border border-white/10 px-3 py-1.5 text-xs text-subtext0 hover:text-text hover:bg-white/5">
              <Plus className="h-3.5 w-3.5" /> New chat
            </button>
          )}
        </div>
      </div>

      {/* conversation */}
      <div className="flex-1 overflow-y-auto px-4 sm:px-6">
        <div className={cn('max-w-3xl mx-auto', empty ? 'h-full flex flex-col justify-center py-8' : 'py-6 space-y-5')}>
          {empty ? (
            <div className="flex flex-col items-center text-center">
              <div className="relative mb-6">
                <span className="absolute inset-0 rounded-[22px] bg-green/30 blur-2xl" aria-hidden />
                <span className="relative w-16 h-16 rounded-[22px] bg-gradient-to-br from-[#4ade80] to-[#15803d] flex items-center justify-center text-black text-2xl font-bold">M</span>
              </div>
              <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-text">{greeting()}.</h1>
              <p className="mt-2 text-sm text-subtext0">What can I take off your plate?</p>

              {summary && (
                <div className="mt-5 flex flex-wrap justify-center gap-2 text-[11px]">
                  <span className="rounded-full bg-white/[0.05] border border-white/[0.06] px-3 py-1 text-subtext1">{summary.counts.today} for today</span>
                  {summary.counts.overdue > 0 && <span className="rounded-full bg-red/10 border border-red/25 px-3 py-1 text-red">{summary.counts.overdue} overdue</span>}
                  {summary.counts.waiting > 0 && <span className="rounded-full bg-yellow/10 border border-yellow/25 px-3 py-1 text-yellow">waiting on {summary.counts.waiting}</span>}
                  {summary.counts.inbox > 0 && <span className="rounded-full bg-white/[0.05] border border-white/[0.06] px-3 py-1 text-subtext1">{summary.counts.inbox} in inbox</span>}
                </div>
              )}

              <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full max-w-xl">
                {SUGGESTIONS.map(s => (
                  <button key={s.title} onClick={() => submit(s.prompt)} disabled={!connected || streaming}
                          className="group flex items-start gap-3 rounded-[18px] border border-white/[0.06] bg-[#0b0b0b] p-3.5 text-left hover:border-green/30 hover:bg-white/[0.03] transition-colors disabled:opacity-50">
                    <span className="w-8 h-8 shrink-0 rounded-xl bg-white/[0.05] flex items-center justify-center group-hover:bg-green/15 transition-colors">
                      <s.icon className="h-4 w-4 text-subtext0 group-hover:text-green transition-colors" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm text-text">{s.title}</span>
                      <span className="block text-[11px] text-overlay1 mt-0.5 line-clamp-2">{s.prompt}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {blocks.map(b => b.kind === 'tools'
                ? <ToolActivity key={b.tools[0].id} tools={b.tools} />
                : <MessageBubble key={b.msg.id} message={b.msg} />)}
              {pendingSkill && (
                <SkillSuggestionCard
                  name={pendingSkill.name}
                  context={pendingSkill.context}
                  onConfirm={() => confirmSkill(pendingSkill.name)}
                  onDismiss={dismissSkill}
                />
              )}
              {awaiting && (
                <div className="flex items-center gap-3" role="status" aria-label="Mayday is thinking">
                  <MaydayAvatar pulse />
                  <div className="flex gap-1">
                    {[0, 150, 300].map(d => (
                      <span key={d} className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" style={{ animationDelay: `${d}ms` }} />
                    ))}
                  </div>
                  <span className="text-xs text-overlay1">Thinking…</span>
                </div>
              )}
            </>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* composer */}
      <div className="shrink-0 px-4 sm:px-6 pb-4 pt-2">
        <div className="max-w-3xl mx-auto">
          <div className={cn(
            'rounded-[22px] border bg-[#0b0b0b] transition-colors',
            'border-white/[0.08] focus-within:border-green/40 focus-within:shadow-[0_0_24px_rgba(34,197,94,0.08)]',
          )}>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={e => { setInput(e.target.value); adjustHeight() }}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  submit()
                }
              }}
              placeholder={connected ? 'Message Mayday…' : 'Connecting to Mayday…'}
              aria-label="Message Mayday"
              disabled={!connected}
              rows={1}
              className="block w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-sm text-text placeholder:text-overlay0 outline-none leading-relaxed"
            />
            <div className="flex items-center gap-1 px-2 pb-2">
              <input ref={fileRef} type="file" accept=".pdf" className="hidden"
                     onChange={e => { uploadPdf(e.target.files?.[0]); e.target.value = '' }} />
              <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading}
                      title="Attach a PDF" aria-label="Attach a PDF"
                      className="w-8 h-8 rounded-full flex items-center justify-center text-overlay1 hover:text-text hover:bg-white/5 disabled:opacity-40">
                <FileText className="h-4 w-4" />
              </button>
              <button type="button" onClick={() => window.dispatchEvent(new CustomEvent('navigate', { detail: 'voice' }))}
                      title="Talk to Mayday" aria-label="Switch to voice"
                      className="w-8 h-8 rounded-full flex items-center justify-center text-overlay1 hover:text-text hover:bg-white/5">
                <Mic className="h-4 w-4" />
              </button>
              <span className="flex-1 text-[10px] text-overlay0 pl-2 hidden sm:block truncate">
                {uploading ? 'Uploading PDF…' : streaming ? 'Mayday is working — you can type your next message' : 'Enter to send · Shift + Enter for a new line'}
              </span>
              <span className="flex-1 sm:hidden" />
              <button type="button" onClick={() => submit()} disabled={!canSend} aria-label="Send message"
                      className={cn('w-8 h-8 rounded-full flex items-center justify-center transition-colors',
                        canSend ? 'bg-green text-black hover:bg-green/90' : 'bg-white/[0.06] text-overlay0')}>
                <ArrowUp className="h-4 w-4" strokeWidth={2.5} />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
