import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, GripVertical } from 'lucide-react'
import { cn } from '../../lib/utils'
import { api } from '../../services/api'
import { usePlannerActions, usePlannerVersion } from '../../hooks/usePlanner'
import {
  addDays, fmtTime, hasTime, itemKey, parseLocal, startOfWeek, toDateStr, toLocalStr, todayStr,
} from '../../lib/planner'
import type { PlannerItem, PlannerItemInput } from '../../types/planner'

type Mode = 'month' | 'week' | 'day'
const HOUR_PX = 48
const FIRST_HOUR = 6
const LAST_HOUR = 23

interface Props {
  onOpen: (item: PlannerItem) => void
  onCreate: (defaults: PlannerItemInput) => void
}

/** Where an item sits on the grid: events by start, tasks by time block, else by due. */
function placement(i: PlannerItem): { start: string; end: string | null } | null {
  if (i.kind === 'event') {
    const s = i.occurrence_at ?? i.start_at
    return s ? { start: s, end: i.end_at } : null
  }
  if (i.scheduled_block) return { start: i.scheduled_block.start, end: i.scheduled_block.end }
  const d = i.occurrence_at ?? i.due_at ?? (i.kind === 'waiting' ? i.follow_up_at : null)
  return d ? { start: d, end: null } : null
}

function chipClass(i: PlannerItem) {
  if (i.status === 'done') return 'bg-white/[0.04] text-overlay1 line-through border-white/[0.06]'
  if (i.kind === 'event') return 'bg-green/20 text-green border-green/30'
  if (i.scheduled_block) return 'bg-white/[0.07] text-text border-green/40 border-dashed'
  if (i.kind === 'waiting') return 'bg-yellow/10 text-yellow border-yellow/25'
  return 'bg-white/[0.05] text-subtext1 border-white/10'
}

export function CalendarView({ onOpen, onCreate }: Props) {
  const version = usePlannerVersion()
  const actions = usePlannerActions()
  const [mode, setMode] = useState<Mode>('week')
  const [cursor, setCursor] = useState(() => new Date())
  const [items, setItems] = useState<PlannerItem[]>([])
  const [unscheduled, setUnscheduled] = useState<PlannerItem[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  const range = useMemo(() => {
    if (mode === 'month') {
      const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
      const start = startOfWeek(first)
      return { start, days: 42 }
    }
    if (mode === 'week') return { start: startOfWeek(cursor), days: 7 }
    return { start: new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate()), days: 1 }
  }, [mode, cursor])

  useEffect(() => {
    let cancelled = false
    const end = addDays(range.start, range.days - 1)
    api.planner.list({ view: 'calendar', start: toDateStr(range.start), end: toDateStr(end), include_done: true })
      .then(r => { if (!cancelled) setItems(r) })
      .catch(() => {})
    api.planner.list({ view: 'all', kind: 'task' })
      .then(r => { if (!cancelled) setUnscheduled(r.filter(t => !t.scheduled_block && !hasTime(t.due_at))) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [range, version])

  useEffect(() => {
    if (mode !== 'month' && scrollRef.current) scrollRef.current.scrollTop = (8 - FIRST_HOUR) * HOUR_PX
  }, [mode])

  const days = Array.from({ length: range.days }, (_, i) => addDays(range.start, i))
  const byDay = useMemo(() => {
    const m = new Map<string, PlannerItem[]>()
    for (const it of items) {
      const p = placement(it)
      if (!p) continue
      const k = p.start.slice(0, 10)
      m.set(k, [...(m.get(k) ?? []), it])
    }
    return m
  }, [items])

  const step = (dir: number) => {
    const d = new Date(cursor)
    if (mode === 'month') d.setMonth(d.getMonth() + dir)
    else d.setDate(d.getDate() + dir * (mode === 'week' ? 7 : 1))
    setCursor(d)
  }

  const title = mode === 'month'
    ? cursor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
    : mode === 'week'
      ? `${days[0].toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} – ${days[6].toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}`
      : cursor.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })

  // ── drag & drop ──
  const onDragStart = (e: React.DragEvent, it: PlannerItem) => {
    const p = placement(it)
    const dur = p?.end && hasTime(p.start) ? (parseLocal(p.end).getTime() - parseLocal(p.start).getTime()) / 60000 : (it.estimate_min ?? 30)
    e.dataTransfer.setData('application/x-planner', JSON.stringify({ id: it.id, kind: it.kind, dur, recurring: !!it.recurrence }))
    e.dataTransfer.effectAllowed = 'move'
  }

  const dropAt = async (e: React.DragEvent, start: Date, allDay = false) => {
    e.preventDefault()
    const raw = e.dataTransfer.getData('application/x-planner')
    if (!raw) return
    const { id, kind, dur, recurring } = JSON.parse(raw) as { id: string; kind: string; dur: number; recurring: boolean }
    if (recurring && !window.confirm('This repeats — move the whole series?')) return
    const s = allDay ? toDateStr(start) : toLocalStr(start)
    if (kind === 'event') {
      await actions.update(id, allDay ? { start_at: s, end_at: null } : { start_at: s, end_at: toLocalStr(new Date(start.getTime() + dur * 60000)) })
    } else if (allDay) {
      await actions.schedule(id, null)
      await actions.update(id, { due_at: s })
    } else {
      await actions.schedule(id, s, toLocalStr(new Date(start.getTime() + dur * 60000)))
    }
  }

  const slotTime = (e: React.MouseEvent | React.DragEvent, day: Date) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const mins = Math.max(0, Math.round(((e.clientY - rect.top) / HOUR_PX) * 60 / 15) * 15)
    const d = new Date(day)
    d.setHours(FIRST_HOUR, 0, 0, 0)
    return new Date(d.getTime() + mins * 60000)
  }

  return (
    <div className="flex flex-col h-full min-h-0 gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <button onClick={() => step(-1)} aria-label="Previous" className="w-8 h-8 rounded-full border border-white/10 flex items-center justify-center text-subtext0 hover:text-text hover:bg-white/5"><ChevronLeft className="h-4 w-4" /></button>
          <button onClick={() => step(1)} aria-label="Next" className="w-8 h-8 rounded-full border border-white/10 flex items-center justify-center text-subtext0 hover:text-text hover:bg-white/5"><ChevronRight className="h-4 w-4" /></button>
          <button onClick={() => setCursor(new Date())} className="ml-1 px-3 h-8 rounded-full border border-white/10 text-xs text-subtext0 hover:text-text hover:bg-white/5">Today</button>
        </div>
        <h2 className="text-base font-medium text-text flex-1 min-w-0 truncate">{title}</h2>
        <div className="flex rounded-[10px] bg-white/[0.04] border border-white/[0.06] p-0.5" role="tablist" aria-label="Calendar range">
          {(['day', 'week', 'month'] as Mode[]).map(m => (
            <button key={m} role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
                    className={cn('px-3 py-1 rounded-[8px] text-[11px] font-medium capitalize transition-colors',
                      mode === m ? 'bg-text text-black' : 'text-subtext0 hover:text-text')}>{m}</button>
          ))}
        </div>
      </div>

      {mode === 'month' ? (
        <div className="flex-1 min-h-0 grid grid-cols-7 grid-rows-[auto_repeat(6,minmax(0,1fr))] gap-px rounded-[20px] overflow-hidden bg-white/[0.05] border border-white/[0.06]">
          {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(d => (
            <div key={d} className="bg-[#0b0b0b] px-2 py-1.5 text-[10px] uppercase tracking-wide text-overlay1">{d}</div>
          ))}
          {days.map(day => {
            const ds = toDateStr(day)
            const list = (byDay.get(ds) ?? []).sort((a, b) => (placement(a)!.start).localeCompare(placement(b)!.start))
            const inMonth = day.getMonth() === cursor.getMonth()
            return (
              <div key={ds}
                   onClick={() => onCreate({ kind: 'event', start_at: ds })}
                   onDragOver={e => e.preventDefault()}
                   onDrop={e => dropAt(e, day, true)}
                   className={cn('bg-[#0b0b0b] p-1.5 min-h-[84px] flex flex-col gap-1 cursor-pointer hover:bg-white/[0.02]', !inMonth && 'opacity-40')}>
                <span className={cn('self-start text-[11px] w-6 h-6 rounded-full flex items-center justify-center',
                  ds === todayStr() ? 'bg-green text-black font-semibold' : 'text-subtext0')}>{day.getDate()}</span>
                {list.slice(0, 3).map(it => (
                  <button key={itemKey(it)} draggable onDragStart={e => onDragStart(e, it)}
                          onClick={e => { e.stopPropagation(); onOpen(it) }}
                          className={cn('text-left truncate rounded-md border px-1.5 py-0.5 text-[10px]', chipClass(it))}>
                    {hasTime(placement(it)!.start) && <span className="opacity-70 mr-1">{fmtTime(placement(it)!.start)}</span>}
                    {it.title}
                  </button>
                ))}
                {list.length > 3 && (
                  <button onClick={e => { e.stopPropagation(); setCursor(day); setMode('day') }}
                          className="text-left text-[10px] text-overlay1 hover:text-text px-1">+{list.length - 3} more</button>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <div className="flex-1 min-h-0 flex gap-3">
          <div className="flex-1 min-w-0 flex flex-col rounded-[20px] bg-[#0b0b0b] border border-white/[0.06] overflow-hidden">
            {/* header + all-day row */}
            <div className="grid border-b border-white/[0.06]" style={{ gridTemplateColumns: `52px repeat(${days.length}, minmax(0,1fr))` }}>
              <div />
              {days.map(day => {
                const ds = toDateStr(day)
                return (
                  <div key={ds} className="px-2 py-2 border-l border-white/[0.04]">
                    <p className="text-[10px] uppercase text-overlay1">{day.toLocaleDateString(undefined, { weekday: 'short' })}</p>
                    <p className={cn('text-lg font-medium leading-tight', ds === todayStr() ? 'text-green' : 'text-text')}>{day.getDate()}</p>
                  </div>
                )
              })}
              <div className="text-[9px] text-overlay1 px-1 py-1 self-center">all-day</div>
              {days.map(day => {
                const ds = toDateStr(day)
                const allDay = (byDay.get(ds) ?? []).filter(it => !hasTime(placement(it)!.start))
                return (
                  <div key={ds} onDragOver={e => e.preventDefault()} onDrop={e => dropAt(e, day, true)}
                       className="min-h-[30px] border-l border-white/[0.04] p-1 flex flex-col gap-0.5">
                    {allDay.map(it => (
                      <button key={itemKey(it)} draggable onDragStart={e => onDragStart(e, it)} onClick={() => onOpen(it)}
                              className={cn('text-left truncate rounded-md border px-1.5 py-0.5 text-[10px]', chipClass(it))}>{it.title}</button>
                    ))}
                  </div>
                )
              })}
            </div>

            {/* time grid */}
            <div ref={scrollRef} className="flex-1 overflow-y-auto">
              <div className="grid relative" style={{ gridTemplateColumns: `52px repeat(${days.length}, minmax(0,1fr))` }}>
                <div>
                  {Array.from({ length: LAST_HOUR - FIRST_HOUR + 1 }, (_, h) => (
                    <div key={h} style={{ height: HOUR_PX }} className="text-[10px] text-overlay1 text-right pr-2 -translate-y-1.5">
                      {new Date(2000, 0, 1, FIRST_HOUR + h).toLocaleTimeString(undefined, { hour: 'numeric' })}
                    </div>
                  ))}
                </div>
                {days.map(day => (
                  <DayColumn key={toDateStr(day)} day={day} items={(byDay.get(toDateStr(day)) ?? []).filter(it => hasTime(placement(it)!.start))}
                             onOpen={onOpen} onDragStart={onDragStart}
                             onDrop={(e) => dropAt(e, slotTime(e, day))}
                             onCreateAt={(e) => onCreate({ kind: 'event', start_at: toLocalStr(slotTime(e, day)) })} />
                ))}
              </div>
            </div>
          </div>

          {/* unscheduled tasks to drag in */}
          <div className="hidden lg:flex w-56 shrink-0 flex-col rounded-[20px] bg-[#0b0b0b] border border-white/[0.06] p-3">
            <p className="text-sm text-subtext1 mb-1">Unscheduled</p>
            <p className="text-[10px] text-overlay1 mb-3">Drag a task onto the calendar to time-block it.</p>
            <div className="flex-1 overflow-y-auto space-y-1.5">
              {unscheduled.length === 0 && <p className="text-[11px] text-overlay1">Nothing waiting for a slot.</p>}
              {unscheduled.map(t => (
                <div key={t.id} draggable onDragStart={e => onDragStart(e, t)} onClick={() => onOpen(t)}
                     className="flex items-center gap-1.5 rounded-xl bg-white/[0.03] border border-white/[0.05] px-2 py-1.5 text-xs text-subtext1 cursor-grab active:cursor-grabbing hover:bg-white/[0.06]">
                  <GripVertical className="h-3 w-3 text-overlay0 shrink-0" />
                  <span className="truncate flex-1">{t.title}</span>
                  <span className="text-[10px] text-overlay1">{t.estimate_min ?? 30}m</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function DayColumn({ day, items, onOpen, onDragStart, onDrop, onCreateAt }: {
  day: Date
  items: PlannerItem[]
  onOpen: (i: PlannerItem) => void
  onDragStart: (e: React.DragEvent, i: PlannerItem) => void
  onDrop: (e: React.DragEvent) => void
  onCreateAt: (e: React.MouseEvent) => void
}) {
  const ds = toDateStr(day)
  const isToday = ds === todayStr()
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    if (!isToday) return
    const t = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(t)
  }, [isToday])

  // lay overlapping items side by side
  const laid = useMemo(() => {
    const evs = items.map(it => {
      const p = placement(it)!
      const s = parseLocal(p.start)
      const e = p.end && hasTime(p.end) ? parseLocal(p.end) : new Date(s.getTime() + (it.estimate_min ?? 30) * 60000)
      return { it, s, e: e > s ? e : new Date(s.getTime() + 15 * 60000) }
    }).sort((a, b) => a.s.getTime() - b.s.getTime())
    const laneEnds: number[] = []
    const withLane = evs.map(ev => {
      let lane = laneEnds.findIndex(end => end <= ev.s.getTime())
      if (lane === -1) { lane = laneEnds.length; laneEnds.push(0) }
      laneEnds[lane] = ev.e.getTime()
      return { ...ev, lane }
    })
    const lanes = Math.max(1, laneEnds.length)
    return withLane.map(ev => ({ ...ev, lanes }))
  }, [items])

  const top = (d: Date) => ((d.getHours() - FIRST_HOUR) * 60 + d.getMinutes()) / 60 * HOUR_PX

  return (
    <div className="relative border-l border-white/[0.04]"
         style={{ height: (LAST_HOUR - FIRST_HOUR + 1) * HOUR_PX }}
         onDragOver={e => e.preventDefault()} onDrop={onDrop}
         onDoubleClick={onCreateAt}
         title="Double-click to add an event">
      {Array.from({ length: LAST_HOUR - FIRST_HOUR + 1 }, (_, h) => (
        <div key={h} style={{ top: h * HOUR_PX }} className="absolute inset-x-0 border-t border-white/[0.04]" />
      ))}
      {isToday && now.getHours() >= FIRST_HOUR && (
        <div style={{ top: top(now) }} className="absolute inset-x-0 z-20 flex items-center pointer-events-none">
          <span className="w-2 h-2 -ml-1 rounded-full bg-green" />
          <span className="flex-1 h-px bg-green" />
        </div>
      )}
      {laid.map(({ it, s, e, lane, lanes }) => {
        const height = Math.max(18, top(e) - top(s))
        return (
          <button key={itemKey(it)} draggable onDragStart={ev => onDragStart(ev, it)}
                  onClick={ev => { ev.stopPropagation(); onOpen(it) }}
                  onDoubleClick={ev => ev.stopPropagation()}
                  style={{ top: Math.max(0, top(s)), height, left: `calc(${(lane / lanes) * 100}% + 2px)`, width: `calc(${100 / lanes}% - 4px)` }}
                  className={cn('absolute z-10 text-left rounded-lg border px-1.5 py-1 overflow-hidden', chipClass(it))}>
            <p className="text-[11px] font-medium leading-tight truncate">{it.title}</p>
            {height > 30 && <p className="text-[10px] opacity-70">{fmtTime(toLocalStr(s))}{it.kind === 'event' || it.scheduled_block ? ` – ${fmtTime(toLocalStr(e))}` : ''}</p>}
          </button>
        )
      })}
    </div>
  )
}
