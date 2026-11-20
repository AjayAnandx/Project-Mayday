import { useEffect, useState } from 'react'
import { Bell, CalendarClock, Check, Mail, Plus, Trash2, X } from 'lucide-react'
import { cn } from '../../lib/utils'
import { WEEKDAYS, describeRecurrence, fmtWhen, hasTime } from '../../lib/planner'
import { usePlannerActions } from '../../hooks/usePlanner'
import type { ItemKind, NudgeResult, Person, PlanRecurrence, PlanReminder, PlannerItem, PlannerItemInput } from '../../types/planner'

const KINDS: { value: ItemKind; label: string }[] = [
  { value: 'task', label: 'Task' },
  { value: 'event', label: 'Event' },
  { value: 'reminder', label: 'Reminder' },
  { value: 'waiting', label: 'Waiting on' },
]

const REMINDER_PRESETS = [
  { v: 0, label: 'At time' }, { v: 5, label: '5 min' }, { v: 10, label: '10 min' }, { v: 15, label: '15 min' },
  { v: 30, label: '30 min' }, { v: 60, label: '1 hour' }, { v: 1440, label: '1 day' },
]

const field = 'w-full rounded-xl bg-white/[0.04] border border-white/[0.08] px-3 py-2 text-sm text-text placeholder:text-overlay0 focus:outline-none focus:border-green/50'
const label = 'block text-[11px] font-medium text-overlay1 mb-1.5'

/** Date + optional time editor for planner 'YYYY-MM-DD[THH:MM]' strings. */
function DateTimeField({ value, onChange, placeholderTime = '09:00', id }: {
  value: string | null; onChange: (v: string | null) => void; placeholderTime?: string; id?: string
}) {
  const date = value?.slice(0, 10) ?? ''
  const time = hasTime(value) ? value!.slice(11, 16) : ''
  return (
    <div className="flex gap-2">
      <input id={id} type="date" value={date} className={cn(field, 'flex-1 [color-scheme:dark]')}
             onChange={e => onChange(e.target.value ? (time ? `${e.target.value}T${time}` : e.target.value) : null)} />
      <input type="time" value={time} disabled={!date} aria-label="Time (optional)" className={cn(field, 'w-[8.5rem] shrink-0 [color-scheme:dark] disabled:opacity-40')}
             placeholder={placeholderTime}
             onChange={e => onChange(e.target.value ? `${date}T${e.target.value}` : date)} />
      {value && (
        <button type="button" onClick={() => onChange(null)} aria-label="Clear date"
                className="px-2 rounded-xl text-overlay1 hover:text-text hover:bg-white/5"><X className="h-4 w-4" /></button>
      )}
    </div>
  )
}

function RecurrenceEditor({ value, onChange }: { value: PlanRecurrence | null; onChange: (v: PlanRecurrence | null) => void }) {
  const freq = value?.freq ?? ''
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <select value={freq} aria-label="Repeat"
                onChange={e => onChange(e.target.value ? { ...(value ?? {}), freq: e.target.value as PlanRecurrence['freq'], interval: value?.interval ?? 1 } : null)}
                className={cn(field, 'flex-1 [color-scheme:dark]')}>
          <option value="">Doesn't repeat</option>
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
          <option value="yearly">Yearly</option>
        </select>
        {value && (
          <label className="flex items-center gap-2 text-xs text-subtext0">
            every
            <input type="number" min={1} value={value.interval ?? 1} aria-label="Repeat interval"
                   onChange={e => onChange({ ...value, interval: Math.max(1, Number(e.target.value) || 1) })}
                   className={cn(field, 'w-16 px-2')} />
          </label>
        )}
      </div>
      {value?.freq === 'weekly' && (
        <div className="flex gap-1" role="group" aria-label="Repeat on days">
          {WEEKDAYS.map((d, i) => {
            const on = value.byweekday?.includes(i)
            return (
              <button key={d} type="button" aria-pressed={on}
                      onClick={() => {
                        const set = new Set(value.byweekday ?? [])
                        if (on) set.delete(i); else set.add(i)
                        onChange({ ...value, byweekday: [...set].sort() })
                      }}
                      className={cn('flex-1 py-1.5 rounded-lg text-[11px] font-medium transition-colors',
                        on ? 'bg-green text-black' : 'bg-white/[0.04] text-subtext0 hover:bg-white/[0.08]')}>
                {d.slice(0, 2)}
              </button>
            )
          })}
        </div>
      )}
      {value && (
        <label className="flex items-center gap-2 text-xs text-subtext0">
          <input type="checkbox" checked={value.repeat_from === 'completion'} className="accent-green"
                 onChange={e => onChange({ ...value, repeat_from: e.target.checked ? 'completion' : 'due' })} />
          Count from when I finish it (e.g. "3 days after I water the plants")
        </label>
      )}
      {value && <p className="text-[11px] text-green/80">{describeRecurrence(value)}</p>}
    </div>
  )
}

export function ItemDrawer({ item, defaults, people, onClose }: {
  item: PlannerItem | null
  /** prefill for a new item (e.g. clicked calendar slot) */
  defaults?: PlannerItemInput
  people: Person[]
  onClose: () => void
}) {
  const actions = usePlannerActions()
  const isNew = !item
  const [d, setD] = useState<PlannerItemInput>({})
  const [personName, setPersonName] = useState('')
  const [newCheck, setNewCheck] = useState('')
  const [blockStart, setBlockStart] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [nudge, setNudge] = useState<NudgeResult | null>(null)

  useEffect(() => {
    const base: PlannerItemInput = item
      ? { ...item }
      : { kind: 'task', title: '', notes: '', tags: [], priority: 4, checklist: [], reminders: null, recurrence: null, ...defaults }
    setD(base)
    setPersonName(people.find(p => p.id === base.person_id)?.name ?? '')
    setBlockStart(item?.scheduled_block?.start ?? null)
    setNudge(null)
    setError(null)
    // reset only when a different item/version or new defaults arrive — not on every
    // background refresh of `people`, which would wipe in-progress edits
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id, item?.updated_at, item?.occurrence_at, JSON.stringify(defaults ?? null)])

  // people may arrive after the drawer opens — fill the name once they do
  const personId = item?.person_id ?? defaults?.person_id
  useEffect(() => {
    if (!personName && personId) {
      const p = people.find(x => x.id === personId)
      if (p) setPersonName(p.name)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [people, personId])

  const set = <K extends keyof PlannerItemInput>(k: K, v: PlannerItemInput[K]) => setD(prev => ({ ...prev, [k]: v }))
  const kind = (d.kind ?? 'task') as ItemKind
  const anchorKey = kind === 'event' ? 'start_at' : 'due_at'
  const reminders = d.reminders

  const save = async () => {
    if (!d.title?.trim()) { setError('Give it a title'); return }
    setSaving(true)
    setError(null)
    try {
      const payload: PlannerItemInput = {
        kind, title: d.title.trim(), notes: d.notes ?? '', list: d.list ?? '', tags: d.tags ?? [],
        priority: d.priority ?? 4, start_at: d.start_at ?? null, due_at: d.due_at ?? null, end_at: d.end_at ?? null,
        all_day: kind === 'event' ? !hasTime(d.start_at) : false, estimate_min: d.estimate_min ?? null,
        reminders: d.reminders ?? null, recurrence: d.recurrence ?? null, checklist: d.checklist ?? [],
        follow_up_at: d.follow_up_at ?? null,
      }
      if (kind === 'waiting') {
        if (!personName.trim()) { setError('Who are you waiting on?'); setSaving(false); return }
        const existing = people.find(p => p.name.toLowerCase() === personName.trim().toLowerCase())
        payload.person_id = existing ? existing.id : (await actions.createPerson({ name: personName.trim() })).id
      } else {
        payload.person_id = null
      }
      const saved = isNew ? await actions.create(payload) : await actions.update(item!.id, payload)
      if (kind === 'task' && (blockStart ?? null) !== (item?.scheduled_block?.start ?? null)) {
        await actions.schedule(saved.id, blockStart)
      }
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const doNudge = async () => {
    if (!item) return
    setNudge(await actions.nudge(item.id))
  }

  return (
    <aside className="flex flex-col h-full rounded-[20px] bg-[#0b0b0b] border border-white/[0.06] overflow-hidden" aria-label={isNew ? 'New item' : 'Edit item'}>
      <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-white/[0.05]">
        <div className="flex rounded-[10px] bg-white/[0.04] border border-white/[0.06] p-0.5" role="tablist" aria-label="Kind">
          {KINDS.map(k => (
            <button key={k.value} role="tab" aria-selected={kind === k.value} onClick={() => set('kind', k.value)}
                    className={cn('px-2.5 py-1 rounded-[8px] text-[11px] font-medium transition-colors',
                      kind === k.value ? 'bg-text text-black' : 'text-subtext0 hover:text-text')}>
              {k.label}
            </button>
          ))}
        </div>
        <button onClick={onClose} aria-label="Close" className="p-1.5 rounded-full text-overlay1 hover:text-text hover:bg-white/5">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        <input autoFocus={isNew} value={d.title ?? ''} onChange={e => set('title', e.target.value)} placeholder="What needs doing?"
               aria-label="Title" className="w-full bg-transparent text-lg font-medium text-text placeholder:text-overlay0 focus:outline-none"
               onKeyDown={e => { if (e.key === 'Enter') save() }} />

        {kind === 'waiting' && (
          <div className="rounded-2xl bg-white/[0.03] border border-white/[0.05] p-3 space-y-3">
            <div>
              <label className={label} htmlFor="pl-person">Waiting on</label>
              <input id="pl-person" list="pl-people" value={personName} onChange={e => setPersonName(e.target.value)}
                     placeholder="Name" className={field} />
              <datalist id="pl-people">{people.map(p => <option key={p.id} value={p.name} />)}</datalist>
            </div>
            <div>
              <label className={label}>Follow up on</label>
              <DateTimeField value={d.follow_up_at ?? null} onChange={v => set('follow_up_at', v)} />
            </div>
            {item && (
              <div className="space-y-2">
                <button onClick={doNudge} className="flex items-center gap-2 rounded-xl bg-green/10 border border-green/25 px-3 py-2 text-xs font-medium text-green hover:bg-green/15">
                  <Mail className="h-3.5 w-3.5" /> Draft a follow-up email
                </button>
                {nudge && (
                  <div className={cn('rounded-xl p-3 text-xs', nudge.drafted ? 'bg-green/10 text-green' : 'bg-white/[0.04] text-subtext0')}>
                    {nudge.drafted
                      ? <>Draft saved in Gmail to {nudge.to}. Review and send it from Gmail or ask Mayday to send it.</>
                      : <>
                          <p className="text-yellow mb-1">Not drafted: {nudge.reason}</p>
                          {nudge.body && <pre className="whitespace-pre-wrap font-sans text-subtext1">{nudge.body}</pre>}
                        </>}
                  </div>
                )}
                {item.chase_log.length > 0 && (
                  <ul className="text-[11px] text-overlay1 space-y-0.5">
                    {item.chase_log.map((c, i) => <li key={i}>Chased {new Date(c.at).toLocaleDateString()} · {c.channel.replace('_', ' ')}</li>)}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}

        <div>
          <label className={label}>{kind === 'event' ? 'Starts' : kind === 'waiting' ? 'Due from them' : 'Due'}</label>
          <DateTimeField value={(d[anchorKey] as string | null) ?? null} onChange={v => set(anchorKey, v)} />
        </div>
        {kind === 'event' && hasTime(d.start_at) && (
          <div>
            <label className={label}>Ends</label>
            <DateTimeField value={d.end_at ?? null} onChange={v => set('end_at', v)} />
          </div>
        )}

        <div>
          <label className={label}>Repeat</label>
          <RecurrenceEditor value={d.recurrence ?? null} onChange={v => set('recurrence', v)} />
        </div>

        {kind !== 'waiting' && (
          <div>
            <label className={cn(label, 'flex items-center gap-1')}><Bell className="h-3 w-3" /> Alerts</label>
            <div className="flex flex-wrap gap-1.5">
              {reminders === null || reminders === undefined ? (
                <span className="text-[11px] text-overlay1 py-1">
                  {kind === 'event' ? 'Default · 30 min before' : hasTime(d.due_at) ? 'Default · at due time' : 'Default · 9 AM nudge on the day'}
                </span>
              ) : reminders.length === 0 ? (
                <span className="text-[11px] text-overlay1 py-1">No alerts</span>
              ) : reminders.map((r: PlanReminder, i) => (
                <span key={r.id ?? i} className="inline-flex items-center gap-1 rounded-lg bg-white/[0.05] px-2 py-1 text-[11px] text-subtext1">
                  {r.at ? fmtWhen(r.at) : REMINDER_PRESETS.find(p => p.v === r.offset_min)?.label ?? `${r.offset_min} min`}{r.at || r.offset_min === 0 ? '' : ' before'}
                  <button onClick={() => set('reminders', reminders.filter((_, j) => j !== i))} aria-label="Remove alert"
                          className="text-overlay1 hover:text-red"><X className="h-3 w-3" /></button>
                </span>
              ))}
              <select value="" aria-label="Add alert" className="rounded-lg bg-white/[0.04] border border-white/[0.08] px-2 py-1 text-[11px] text-subtext0 [color-scheme:dark]"
                      onChange={e => {
                        if (e.target.value === 'none') set('reminders', [])
                        else if (e.target.value === 'default') set('reminders', null)
                        else set('reminders', [...(reminders ?? []), { offset_min: Number(e.target.value) }])
                      }}>
                <option value="">+ Alert</option>
                {REMINDER_PRESETS.map(p => <option key={p.v} value={p.v}>{p.label}{p.v ? ' before' : ''}</option>)}
                <option value="default">Use default</option>
                <option value="none">No alerts</option>
              </select>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={label} htmlFor="pl-priority">Priority</label>
            <select id="pl-priority" value={d.priority ?? 4} onChange={e => set('priority', Number(e.target.value))} className={cn(field, '[color-scheme:dark]')}>
              <option value={1}>High</option><option value={2}>Medium</option><option value={3}>Low</option><option value={4}>None</option>
            </select>
          </div>
          <div>
            <label className={label} htmlFor="pl-list">List</label>
            <input id="pl-list" value={d.list ?? ''} onChange={e => set('list', e.target.value)} placeholder="Home, Work…" className={field} />
          </div>
        </div>

        <div>
          <label className={label} htmlFor="pl-tags">Tags</label>
          <input id="pl-tags" value={(d.tags ?? []).join(', ')} placeholder="errand, finance"
                 onChange={e => set('tags', e.target.value.split(',').map(t => t.trim().replace(/^#/, '')).filter(Boolean))}
                 className={field} />
        </div>

        {kind === 'task' && (
          <div className="grid grid-cols-[1fr_auto] gap-3 items-end">
            <div>
              <label className={cn(label, 'flex items-center gap-1')}><CalendarClock className="h-3 w-3" /> Time-block on calendar</label>
              <DateTimeField value={blockStart} onChange={v => setBlockStart(v && !hasTime(v) ? `${v}T09:00` : v)} />
            </div>
            <div>
              <label className={label} htmlFor="pl-est">Minutes</label>
              <input id="pl-est" type="number" min={5} step={5} value={d.estimate_min ?? ''} placeholder="30"
                     onChange={e => set('estimate_min', e.target.value ? Number(e.target.value) : null)} className={cn(field, 'w-20')} />
            </div>
          </div>
        )}

        <div>
          <label className={label}>Checklist</label>
          <ul className="space-y-1">
            {(d.checklist ?? []).map((c, i) => (
              <li key={c.id ?? i} className="flex items-center gap-2 group">
                <button onClick={() => set('checklist', (d.checklist ?? []).map((x, j) => j === i ? { ...x, done: !x.done } : x))}
                        aria-label={c.done ? 'Uncheck' : 'Check'}
                        className={cn('w-4 h-4 rounded-md border flex items-center justify-center', c.done ? 'bg-green border-green' : 'border-overlay0')}>
                  {c.done && <Check className="h-3 w-3 text-black" strokeWidth={3} />}
                </button>
                <span className={cn('flex-1 text-sm', c.done ? 'line-through text-overlay1' : 'text-subtext1')}>{c.text}</span>
                <button onClick={() => set('checklist', (d.checklist ?? []).filter((_, j) => j !== i))} aria-label="Remove step"
                        className="opacity-0 group-hover:opacity-100 text-overlay1 hover:text-red"><X className="h-3.5 w-3.5" /></button>
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-2 mt-1.5">
            <Plus className="h-3.5 w-3.5 text-overlay1" />
            <input value={newCheck} onChange={e => setNewCheck(e.target.value)} placeholder="Add a step"
                   onKeyDown={e => {
                     if (e.key === 'Enter' && newCheck.trim()) {
                       set('checklist', [...(d.checklist ?? []), { text: newCheck.trim(), done: false }])
                       setNewCheck('')
                     }
                   }}
                   className="flex-1 bg-transparent text-sm text-text placeholder:text-overlay0 focus:outline-none" />
          </div>
        </div>

        <div>
          <label className={label} htmlFor="pl-notes">Notes</label>
          <textarea id="pl-notes" rows={3} value={d.notes ?? ''} onChange={e => set('notes', e.target.value)} className={cn(field, 'resize-y')} />
        </div>

        {item?.completions && item.completions.length > 0 && (
          <p className="text-[11px] text-overlay1">Completed {item.completions.length}× · last {new Date(item.completions[item.completions.length - 1].at).toLocaleDateString()}</p>
        )}
      </div>

      <div className="flex items-center gap-2 px-5 py-3 border-t border-white/[0.05]">
        {error && <p className="flex-1 text-xs text-red">{error}</p>}
        {!error && <span className="flex-1" />}
        {item && (
          <button onClick={async () => { await actions.remove(item.id); onClose() }}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs text-red hover:bg-red/10">
            <Trash2 className="h-3.5 w-3.5" /> Delete
          </button>
        )}
        <button onClick={save} disabled={saving}
                className="px-4 py-2 rounded-xl bg-green text-black text-xs font-semibold hover:bg-green/90 disabled:opacity-60">
          {saving ? 'Saving…' : isNew ? 'Add' : 'Save'}
        </button>
      </div>
    </aside>
  )
}
