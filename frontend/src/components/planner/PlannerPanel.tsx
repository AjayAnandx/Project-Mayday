import { useMemo, useState } from 'react'
import {
  CalendarDays, CalendarRange, CheckCircle2, Hash, Hourglass, Inbox, ListTodo, Mail, Plus, Sun, Users,
} from 'lucide-react'
import { cn } from '../../lib/utils'
import { anchorOf, fmtDay, hasTime, isOverdue, itemKey, todayStr } from '../../lib/planner'
import { usePlanner, usePlannerActions } from '../../hooks/usePlanner'
import { QuickAdd } from './QuickAdd'
import { ItemRow } from './ItemRow'
import { ItemDrawer } from './ItemDrawer'
import { CalendarView } from './CalendarView'
import { WaitingBoard } from './WaitingBoard'
import { PeopleView } from './PeopleView'
import { PlanDayPanel } from './PlanDayPanel'
import { DigestModal } from './DigestModal'
import type { PlannerItem, PlannerItemInput, PlannerView } from '../../types/planner'

type Section = PlannerView | 'people'

const NAV: { id: Section; label: string; icon: typeof Sun; count?: 'today' | 'inbox' | 'upcoming' | 'waiting' }[] = [
  { id: 'today', label: 'Today', icon: Sun, count: 'today' },
  { id: 'inbox', label: 'Inbox', icon: Inbox, count: 'inbox' },
  { id: 'upcoming', label: 'Upcoming', icon: CalendarRange, count: 'upcoming' },
  { id: 'waiting', label: 'Waiting on', icon: Hourglass, count: 'waiting' },
  { id: 'calendar', label: 'Calendar', icon: CalendarDays },
  { id: 'people', label: 'People', icon: Users },
  { id: 'done', label: 'Logbook', icon: CheckCircle2 },
]

function Group({ title, tone, children }: { title: string; tone?: 'red' | 'green'; children: React.ReactNode }) {
  return (
    <section className="space-y-1.5">
      <h3 className={cn('text-xs font-medium px-1', tone === 'red' ? 'text-red' : tone === 'green' ? 'text-green' : 'text-subtext0')}>{title}</h3>
      {children}
    </section>
  )
}

function Empty({ icon: Icon, title, hint }: { icon: typeof Sun; title: string; hint: string }) {
  return (
    <div className="rounded-[20px] bg-hatch border border-white/[0.04] flex flex-col items-center justify-center gap-2 py-16 text-center px-6">
      <Icon className="h-6 w-6 text-overlay1" />
      <p className="text-sm text-subtext0">{title}</p>
      <p className="text-[11px] text-overlay1 max-w-sm">{hint}</p>
    </div>
  )
}

export function PlannerPanel() {
  const [section, setSection] = useState<Section>('today')
  const [listFilter, setListFilter] = useState<string | undefined>()
  const [tagFilter, setTagFilter] = useState<string | undefined>()
  const [selected, setSelected] = useState<PlannerItem | null>(null)
  const [creating, setCreating] = useState<PlannerItemInput | null>(null)
  const [digestOpen, setDigestOpen] = useState(false)

  const filtered = !!(listFilter || tagFilter)
  const view: PlannerView = filtered ? 'all' : section === 'people' ? 'all' : section
  const { items, summary, people, loading, error } = usePlanner({ view, list: listFilter, tag: tagFilter })
  const actions = usePlannerActions()

  const go = (s: Section) => { setSection(s); setListFilter(undefined); setTagFilter(undefined) }
  const open = (i: PlannerItem) => { setCreating(null); setSelected(i) }
  const newItem = (defaults: PlannerItemInput) => { setSelected(null); setCreating(defaults) }
  const closeDrawer = () => { setSelected(null); setCreating(null) }
  const toggle = (i: PlannerItem) => actions.complete(i.id, i.status !== 'done')
  const snooze = (i: PlannerItem) => actions.snooze(i.id, { minutes: 60 })
  const del = (i: PlannerItem) => actions.remove(i.id)

  const row = (i: PlannerItem, showDay = true) => (
    <ItemRow key={itemKey(i)} item={i} people={people} selected={selected?.id === i.id} showDay={showDay}
             onOpen={open} onComplete={toggle} onSnooze={snooze} onDelete={del} />
  )

  const today = useMemo(() => {
    const t = todayStr()
    const overdue = items.filter(i => isOverdue(i) && (i.due_at ?? '').slice(0, 10) < t)
    const schedule = items.filter(i => !overdue.includes(i) && (i.kind === 'event' || (i.scheduled_block?.start ?? '').startsWith(t) || (hasTime(i.due_at) && i.kind !== 'waiting')))
      .sort((a, b) => (anchorOf(a) ?? '').localeCompare(anchorOf(b) ?? ''))
    const followUps = items.filter(i => i.kind === 'waiting' && !overdue.includes(i))
    const rest = items.filter(i => !overdue.includes(i) && !schedule.includes(i) && !followUps.includes(i))
    return { overdue, schedule, rest, followUps }
  }, [items])

  const upcoming = useMemo(() => {
    const m = new Map<string, PlannerItem[]>()
    for (const i of items) {
      const k = (anchorOf(i) ?? '').slice(0, 10)
      if (k) m.set(k, [...(m.get(k) ?? []), i])
    }
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [items])

  const heading = listFilter ? listFilter : tagFilter ? `#${tagFilter}` : NAV.find(n => n.id === section)?.label ?? ''
  const drawerOpen = !!(selected || creating)

  let body: React.ReactNode
  if (error) body = <p className="text-xs text-red">{error}</p>
  else if (section === 'calendar' && !filtered) body = <CalendarView onOpen={open} onCreate={newItem} />
  else if (section === 'people' && !filtered) body = <PeopleView people={people} onOpen={open} />
  else if (section === 'waiting' && !filtered) body = <WaitingBoard items={items} people={people} onOpen={open} onNew={() => newItem({ kind: 'waiting' })} />
  else if (loading && items.length === 0) body = <p className="text-xs text-overlay1 px-1">Loading…</p>
  else if (section === 'today' && !filtered) {
    body = (
      <div className="space-y-5">
        <PlanDayPanel />
        {items.length === 0 && <Empty icon={Sun} title="Nothing due today" hint="Enjoy it — or add something with the bar above. Try “Call mom tomorrow 6pm”." />}
        {today.overdue.length > 0 && <Group title={`Overdue · ${today.overdue.length}`} tone="red">{today.overdue.map(i => row(i))}</Group>}
        {today.schedule.length > 0 && <Group title="Schedule" tone="green">{today.schedule.map(i => row(i, false))}</Group>}
        {today.rest.length > 0 && <Group title="Due today">{today.rest.map(i => row(i, false))}</Group>}
        {today.followUps.length > 0 && <Group title="Follow up today">{today.followUps.map(i => row(i))}</Group>}
      </div>
    )
  } else if (section === 'upcoming' && !filtered) {
    body = upcoming.length === 0
      ? <Empty icon={CalendarRange} title="Nothing in the next two weeks" hint="Dated tasks, events and follow-ups show up here, grouped by day." />
      : <div className="space-y-5">{upcoming.map(([day, list]) => <Group key={day} title={fmtDay(day)}>{list.map(i => row(i, false))}</Group>)}</div>
  } else {
    body = items.length === 0
      ? <Empty icon={section === 'inbox' ? Inbox : ListTodo}
               title={section === 'inbox' ? 'Inbox zero' : 'Nothing here'}
               hint={section === 'inbox' ? 'Undated tasks land here. Give them a date or a list to file them.' : 'Try another view.'} />
      : <div className="space-y-1.5">{items.map(i => row(i))}</div>
  }

  return (
    <div className="h-full overflow-hidden bg-crust">
      <div className="h-full max-w-[1400px] mx-auto px-3 sm:px-6 pt-5 pb-4 flex flex-col gap-4">
        <div className="flex flex-col lg:flex-row gap-4 flex-1 min-h-0">
          {/* rail */}
          <nav aria-label="Planner views" className="lg:w-52 shrink-0 flex lg:flex-col gap-1 overflow-x-auto lg:overflow-visible [scrollbar-width:none]">
            {NAV.map(n => {
              const active = section === n.id && !filtered
              const count = n.count ? summary?.counts[n.count] : undefined
              return (
                <button key={n.id} onClick={() => go(n.id)} aria-current={active ? 'page' : undefined}
                        className={cn('flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm whitespace-nowrap transition-colors',
                          active ? 'bg-white/[0.08] text-text' : 'text-subtext0 hover:text-text hover:bg-white/[0.04]')}>
                  <n.icon className={cn('h-4 w-4 shrink-0', active ? 'text-green' : '')} />
                  <span className="flex-1 text-left">{n.label}</span>
                  {n.id === 'today' && (summary?.counts.overdue ?? 0) > 0 && (
                    <span className="rounded-md bg-red px-1.5 text-[10px] font-semibold text-white">{summary!.counts.overdue}</span>
                  )}
                  {count ? <span className="text-[11px] text-overlay1 tabular-nums">{count}</span> : null}
                </button>
              )
            })}
            {(summary?.lists.length ?? 0) > 0 && <p className="hidden lg:block text-[10px] uppercase tracking-wide text-overlay0 px-3 pt-4 pb-1">Lists</p>}
            {summary?.lists.map(l => (
              <button key={l.name} onClick={() => { setListFilter(l.name); setTagFilter(undefined) }}
                      className={cn('flex items-center gap-2.5 px-3 py-1.5 rounded-xl text-sm whitespace-nowrap',
                        listFilter === l.name ? 'bg-white/[0.08] text-text' : 'text-subtext0 hover:text-text hover:bg-white/[0.04]')}>
                <ListTodo className="h-4 w-4" /><span className="flex-1 text-left">{l.name}</span>
                <span className="text-[11px] text-overlay1">{l.open}</span>
              </button>
            ))}
            {(summary?.tags.length ?? 0) > 0 && <p className="hidden lg:block text-[10px] uppercase tracking-wide text-overlay0 px-3 pt-4 pb-1">Tags</p>}
            <div className="flex lg:flex-wrap gap-1 lg:px-2">
              {summary?.tags.map(t => (
                <button key={t} onClick={() => { setTagFilter(t); setListFilter(undefined) }}
                        className={cn('flex items-center gap-0.5 rounded-lg px-2 py-1 text-[11px] whitespace-nowrap',
                          tagFilter === t ? 'bg-green text-black' : 'bg-white/[0.04] text-subtext0 hover:text-text')}>
                  <Hash className="h-3 w-3" />{t}
                </button>
              ))}
            </div>
            <button onClick={() => setDigestOpen(true)}
                    className="lg:mt-4 flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm text-subtext0 hover:text-text hover:bg-white/[0.04] whitespace-nowrap">
              <Mail className="h-4 w-4" /> Email digest
            </button>
          </nav>

          {/* main */}
          <main className="flex-1 min-w-0 min-h-0 flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <h1 className="text-xl sm:text-2xl font-medium text-text tracking-tight flex-1">{heading}</h1>
              <button onClick={() => newItem(section === 'waiting' ? { kind: 'waiting' } : section === 'calendar' ? { kind: 'event', start_at: todayStr() } : { kind: 'task' })}
                      className="flex items-center gap-1.5 rounded-xl bg-green text-black text-xs font-semibold px-3 py-2 hover:bg-green/90">
                <Plus className="h-3.5 w-3.5" /> New
              </button>
            </div>
            <QuickAdd onAdd={t => actions.quickAdd(t)} />
            <div className={cn('flex-1 min-h-0', section === 'calendar' && !filtered ? 'flex flex-col' : 'overflow-y-auto pr-1 pb-6')}>
              {body}
            </div>
          </main>

          {/* drawer */}
          {drawerOpen && (
            <div className="fixed inset-0 z-40 bg-black/60 lg:hidden" onClick={closeDrawer} aria-hidden />
          )}
          {drawerOpen && (
            <div className="fixed inset-y-3 right-3 left-3 sm:left-auto sm:w-[400px] z-50 lg:static lg:z-auto lg:w-[380px] lg:shrink-0 lg:min-h-0">
              <ItemDrawer item={selected} defaults={creating ?? undefined} people={people} onClose={closeDrawer} />
            </div>
          )}
        </div>
      </div>
      <DigestModal open={digestOpen} onClose={() => setDigestOpen(false)} />
    </div>
  )
}
