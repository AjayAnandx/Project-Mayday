import type { PlannerItem, PlanRecurrence } from '../types/planner'

/** Planner times are local wall-clock strings: 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM'. */
export const hasTime = (v?: string | null) => !!v && v.length > 10

export function parseLocal(v: string): Date {
  // new Date('YYYY-MM-DD') is UTC — build from parts so it stays local
  const [d, t] = v.split('T')
  const [y, m, day] = d.split('-').map(Number)
  const [hh, mm] = (t ?? '00:00').split(':').map(Number)
  return new Date(y, m - 1, day, hh, mm)
}

const pad = (n: number) => String(n).padStart(2, '0')
export const toDateStr = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
export const toLocalStr = (d: Date) => `${toDateStr(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`
export const todayStr = () => toDateStr(new Date())

export function addDays(d: Date, n: number) {
  const x = new Date(d)
  x.setDate(x.getDate() + n)
  return x
}

export function startOfWeek(d: Date) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7)) // Monday
  return x
}

export function fmtTime(v: string) {
  return parseLocal(v).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export function fmtDay(v: string) {
  const d = parseLocal(v)
  const today = new Date()
  const diff = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
    - new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()) / 86_400_000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tomorrow'
  if (diff === -1) return 'Yesterday'
  if (diff > 1 && diff < 7) return d.toLocaleDateString(undefined, { weekday: 'long' })
  return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
}

export function fmtWhen(v?: string | null) {
  if (!v) return ''
  return hasTime(v) ? `${fmtDay(v)} ${fmtTime(v)}` : fmtDay(v)
}

/** The time that places an item on the timeline. */
export function anchorOf(i: PlannerItem): string | null {
  return i.occurrence_at
    ?? (i.kind === 'event' ? i.start_at : null)
    ?? i.scheduled_block?.start
    ?? i.due_at
    ?? (i.kind === 'waiting' ? i.follow_up_at : null)
}

export function isOverdue(i: PlannerItem) {
  if (i.status !== 'open' || i.kind === 'event' || !i.due_at) return false
  return hasTime(i.due_at) ? parseLocal(i.due_at) < new Date() : i.due_at < todayStr()
}

export const PRIORITY = {
  1: { label: 'High', dot: 'bg-red', text: 'text-red' },
  2: { label: 'Medium', dot: 'bg-yellow', text: 'text-yellow' },
  3: { label: 'Low', dot: 'bg-green', text: 'text-green' },
  4: { label: 'None', dot: 'bg-overlay0', text: 'text-overlay1' },
} as const

export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export function describeRecurrence(r?: PlanRecurrence | null) {
  if (!r) return ''
  const unit = { daily: 'day', weekly: 'week', monthly: 'month', yearly: 'year' }[r.freq]
  const n = r.interval ?? 1
  let s = n === 1 ? `Every ${unit}` : `Every ${n} ${unit}s`
  if (r.byweekday?.length) {
    s = r.byweekday.length === 5 && r.byweekday.every((d, i) => d === i)
      ? 'Every weekday'
      : `${s} on ${r.byweekday.map(d => WEEKDAYS[d]).join(', ')}`
  }
  if (r.bymonthday) s += ` on the ${r.bymonthday}${ordinal(r.bymonthday)}`
  if (r.repeat_from === 'completion') s += ' after done'
  return s
}

function ordinal(n: number) {
  if (n % 100 >= 11 && n % 100 <= 13) return 'th'
  return ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'
}

/** Stable React key: recurring instances share an id. */
export const itemKey = (i: PlannerItem) => `${i.id}:${i.occurrence_at ?? ''}`

/** Broadcast so every planner view (and the dashboard) refetches. */
export const notifyPlannerChanged = () => window.dispatchEvent(new CustomEvent('planner-changed'))
