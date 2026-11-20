import { useEffect, useRef, useState } from 'react'
import { Bell, CalendarDays, CornerDownLeft, Hourglass, ListTodo, Repeat, Tag, User, Flag, Clock } from 'lucide-react'
import { api } from '../../services/api'
import { describeRecurrence, fmtWhen } from '../../lib/planner'
import type { QuickAddParse } from '../../types/planner'

const KIND = {
  task: { icon: ListTodo, label: 'Task' },
  event: { icon: CalendarDays, label: 'Event' },
  reminder: { icon: Bell, label: 'Reminder' },
  waiting: { icon: Hourglass, label: 'Waiting on' },
} as const

function Chip({ icon: Icon, children }: { icon: typeof Tag; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-green/10 border border-green/20 px-1.5 py-0.5 text-[11px] text-green">
      <Icon className="h-3 w-3" />{children}
    </span>
  )
}

/** Natural-language capture: "Ravi to send the deck by fri #work !p1". */
export function QuickAdd({ onAdd }: { onAdd: (text: string) => Promise<unknown> }) {
  const [text, setText] = useState('')
  const [parsed, setParsed] = useState<QuickAddParse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!text.trim()) { setParsed(null); return }
    const t = setTimeout(() => {
      api.planner.quickAdd(text, false).then(r => setParsed(r.parsed)).catch(() => setParsed(null))
    }, 180)
    return () => clearTimeout(t)
  }, [text])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (e.key === 'q' && !e.ctrlKey && !e.metaKey && tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT') {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const submit = async () => {
    if (!text.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      await onAdd(text.trim())
      setText('')
      setParsed(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not add')
    } finally {
      setBusy(false)
    }
  }

  const when = parsed?.start_at ?? parsed?.due_at
  const kind = parsed ? KIND[parsed.kind] : null

  return (
    <div className="rounded-[20px] bg-[#0b0b0b] border border-white/[0.06] focus-within:border-green/40 transition-colors">
      <div className="flex items-center gap-3 px-4 py-3">
        <span className="w-6 h-6 rounded-lg bg-green/15 flex items-center justify-center shrink-0 text-green text-lg leading-none">+</span>
        <input
          ref={inputRef}
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') submit(); if (e.key === 'Escape') { setText(''); inputRef.current?.blur() } }}
          placeholder='Add anything — "Pay rent every month on the 1st at 9am #home !p1"  ·  "Ravi to send the deck by friday"'
          aria-label="Quick add to planner"
          className="flex-1 min-w-0 bg-transparent text-sm text-text placeholder:text-overlay0 focus:outline-none"
        />
        <kbd className="hidden sm:inline-flex items-center gap-1 text-[10px] text-overlay1 border border-white/10 rounded-md px-1.5 py-0.5">
          {text ? <><CornerDownLeft className="h-3 w-3" /> add</> : 'Q'}
        </kbd>
      </div>
      {(parsed || error) && (
        <div className="flex flex-wrap items-center gap-1.5 px-4 pb-3 -mt-1">
          {error && <span className="text-[11px] text-red">{error}</span>}
          {parsed && kind && (
            <>
              <span className="text-[11px] text-overlay1 mr-1 truncate max-w-[40%]">“{parsed.title}”</span>
              <Chip icon={kind.icon}>{kind.label}</Chip>
              {parsed.person && <Chip icon={User}>{parsed.person}</Chip>}
              {when && <Chip icon={Clock}>{fmtWhen(when)}</Chip>}
              {parsed.recurrence && <Chip icon={Repeat}>{describeRecurrence(parsed.recurrence)}</Chip>}
              {parsed.priority && parsed.priority < 4 && <Chip icon={Flag}>P{parsed.priority}</Chip>}
              {parsed.list && <Chip icon={ListTodo}>{parsed.list}</Chip>}
              {parsed.tags?.map(t => <Chip key={t} icon={Tag}>{t}</Chip>)}
              {parsed.estimate_min && <Chip icon={Clock}>{parsed.estimate_min}m</Chip>}
            </>
          )}
        </div>
      )}
    </div>
  )
}
