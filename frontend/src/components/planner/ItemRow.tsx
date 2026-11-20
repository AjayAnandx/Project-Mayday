import { AlarmClock, Bell, CalendarDays, Check, Clock, Hourglass, Repeat, Trash2, User } from 'lucide-react'
import { cn } from '../../lib/utils'
import { PRIORITY, describeRecurrence, fmtTime, fmtWhen, hasTime, isOverdue } from '../../lib/planner'
import type { Person, PlannerItem } from '../../types/planner'

interface ItemRowProps {
  item: PlannerItem
  people: Person[]
  selected?: boolean
  /** show the day as well as the time (lists spanning several days) */
  showDay?: boolean
  onOpen: (item: PlannerItem) => void
  onComplete: (item: PlannerItem) => void
  onSnooze?: (item: PlannerItem) => void
  onDelete?: (item: PlannerItem) => void
}

const KIND_ICON = { event: CalendarDays, reminder: Bell, waiting: Hourglass, task: null } as const

export function ItemRow({ item, people, selected, showDay = true, onOpen, onComplete, onSnooze, onDelete }: ItemRowProps) {
  const done = item.status === 'done'
  const overdue = isOverdue(item)
  const person = people.find(p => p.id === item.person_id)
  const KindIcon = KIND_ICON[item.kind]
  const when = item.kind === 'event' ? (item.occurrence_at ?? item.start_at) : item.due_at
  const pr = PRIORITY[(item.priority as 1 | 2 | 3 | 4) ?? 4] ?? PRIORITY[4]
  const checkable = item.kind !== 'event'

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(item)}
      onKeyDown={e => { if (e.key === 'Enter') onOpen(item) }}
      className={cn(
        'group flex items-start gap-3 rounded-2xl border px-3 py-2.5 cursor-pointer transition-colors',
        selected ? 'bg-white/[0.06] border-green/30' : 'bg-white/[0.02] border-white/[0.05] hover:bg-white/[0.04]',
      )}
    >
      {checkable ? (
        <button
          onClick={e => { e.stopPropagation(); onComplete(item) }}
          aria-label={done ? `Reopen ${item.title}` : `Complete ${item.title}`}
          className={cn(
            'mt-0.5 w-[18px] h-[18px] shrink-0 rounded-full border-2 flex items-center justify-center transition-colors',
            done ? 'bg-green border-green' : item.priority === 1 ? 'border-red hover:bg-red/20'
              : item.priority === 2 ? 'border-yellow hover:bg-yellow/20' : 'border-overlay0 hover:border-green hover:bg-green/10',
          )}
        >
          {done && <Check className="h-3 w-3 text-black" strokeWidth={3} />}
        </button>
      ) : (
        <span className="mt-0.5 w-[18px] h-[18px] shrink-0 rounded-md bg-green/15 flex items-center justify-center">
          <CalendarDays className="h-3 w-3 text-green" />
        </span>
      )}

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          {KindIcon && item.kind !== 'event' && <KindIcon className="h-3.5 w-3.5 text-overlay2 shrink-0" />}
          <p className={cn('text-sm truncate', done ? 'line-through text-overlay1' : 'text-text')}>{item.title}</p>
        </div>
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 mt-1 text-[11px] text-overlay1">
          {when && (
            <span className={cn('flex items-center gap-1', overdue && 'text-red')}>
              <Clock className="h-3 w-3" />
              {item.kind === 'event' && hasTime(when) && item.end_at && !showDay
                ? `${fmtTime(when)} – ${fmtTime(item.end_at)}`
                : showDay ? fmtWhen(when) : hasTime(when) ? fmtTime(when) : item.kind === 'event' ? 'All day' : 'Any time'}
            </span>
          )}
          {item.scheduled_block && (
            <span className="flex items-center gap-1 text-green/80">
              <CalendarDays className="h-3 w-3" />{fmtWhen(item.scheduled_block.start)}
            </span>
          )}
          {item.kind === 'waiting' && (
            <span className="flex items-center gap-1 text-subtext0">
              <User className="h-3 w-3" />{person?.name ?? 'Someone'}
              {item.follow_up_at && <span className="text-overlay1">· follow up {fmtWhen(item.follow_up_at)}</span>}
            </span>
          )}
          {item.recurrence && (
            <span className="flex items-center gap-1"><Repeat className="h-3 w-3" />{describeRecurrence(item.recurrence)}</span>
          )}
          {item.snoozed_until && (
            <span className="flex items-center gap-1 text-yellow"><AlarmClock className="h-3 w-3" />{fmtWhen(item.snoozed_until)}</span>
          )}
          {item.checklist.length > 0 && (
            <span>{item.checklist.filter(c => c.done).length}/{item.checklist.length}</span>
          )}
          {item.list && <span className="text-subtext0">{item.list}</span>}
          {item.tags.map(t => <span key={t} className="text-green/70">#{t}</span>)}
          {item.priority < 4 && !done && <span className={pr.text}>{pr.label}</span>}
        </div>
      </div>

      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
        {onSnooze && !done && (
          <button
            onClick={e => { e.stopPropagation(); onSnooze(item) }}
            title="Snooze 1 hour"
            aria-label={`Snooze ${item.title}`}
            className="p-1.5 rounded-lg text-overlay1 hover:text-yellow hover:bg-white/5"
          >
            <AlarmClock className="h-3.5 w-3.5" />
          </button>
        )}
        {onDelete && (
          <button
            onClick={e => { e.stopPropagation(); onDelete(item) }}
            title="Delete"
            aria-label={`Delete ${item.title}`}
            className="p-1.5 rounded-lg text-overlay1 hover:text-red hover:bg-white/5"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}
