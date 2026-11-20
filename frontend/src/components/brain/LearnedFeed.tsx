import { useState } from 'react'
import { Check, X, Pencil, Lightbulb, ListChecks, Sparkles, Lock, Quote, GraduationCap } from 'lucide-react'
import { useLearned, type LearnedItem, type LearnedFilter } from '../../hooks/useLearned'

const FILTERS: { key: LearnedFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'pending', label: 'Needs a look' },
  { key: 'active', label: 'Remembered' },
]

function when(iso: string) {
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function KindIcon({ kind }: { kind: LearnedItem['kind'] }) {
  const cls = 'h-3.5 w-3.5 shrink-0'
  if (kind === 'idea') return <Lightbulb className={`${cls} text-yellow`} />
  if (kind === 'commitment') return <ListChecks className={`${cls} text-blue-400`} />
  if (kind === 'lesson') return <GraduationCap className={`${cls} text-purple-400`} />
  return <Sparkles className={`${cls} text-green`} />
}

function Row({ item, onConfirm, onReject, onEdit }: {
  item: LearnedItem
  onConfirm: () => void
  onReject: () => void
  onEdit: (v: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(item.object ?? '')
  const pending = item.status === 'pending'
  const inactive = item.status === 'superseded' || item.status === 'rejected'

  return (
    <li className={`group rounded-xl border px-3 py-2.5 transition-colors ${pending ? 'border-yellow/30 bg-yellow/5' : 'border-surface1 bg-surface0/60'} ${inactive ? 'opacity-50' : ''}`}>
      <div className="flex items-start gap-2">
        <div className="mt-0.5"><KindIcon kind={item.kind} /></div>
        <div className="min-w-0 flex-1">
          {editing ? (
            <form
              className="flex items-center gap-2"
              onSubmit={(e) => { e.preventDefault(); if (value.trim()) { onEdit(value.trim()); setEditing(false) } }}
            >
              <span className="text-xs text-subtext0 shrink-0">{item.subject} {item.predicate?.replace(/_/g, ' ')}</span>
              <input
                autoFocus
                value={value}
                onChange={(e) => setValue(e.target.value)}
                className="flex-1 min-w-0 px-2 py-1 text-xs bg-surface1 border border-surface2 rounded-lg text-text focus:outline-none focus:ring-1 focus:ring-green/50"
              />
              <button type="submit" className="text-xs text-green hover:underline">Save</button>
              <button type="button" onClick={() => setEditing(false)} className="text-xs text-overlay1 hover:underline">Cancel</button>
            </form>
          ) : (
            <p className="text-sm text-text break-words">
              {item.text}
              {item.due && <span className="ml-1.5 text-xs text-overlay1">due {item.due}</span>}
            </p>
          )}
          {item.quote && (
            <p className="mt-1 flex items-start gap-1 text-xs text-overlay1 italic break-words">
              <Quote className="h-3 w-3 mt-0.5 shrink-0" />
              <span>{item.quote}</span>
            </p>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-overlay0">
            <span>{when(item.created_at)}</span>
            {typeof item.confidence === 'number' && <span>· {Math.round(item.confidence * 100)}% sure</span>}
            {pending && <span className="text-yellow">· waiting for you</span>}
            {item.status === 'superseded' && <span>· replaced by a newer value</span>}
            {item.status === 'rejected' && <span>· marked wrong</span>}
            {item.sensitivity === 'private' && (
              <span className="inline-flex items-center gap-0.5"><Lock className="h-3 w-3" /> private, never sent by default</span>
            )}
            {item.planner_item_id && <span>· added to Planner</span>}
            {item.kind === 'lesson' && <span>· lesson from a mistake{item.votes ? ` · seen ${item.votes}×` : ''}{item.uses ? ` · used ${item.uses}×` : ''}</span>}
          </div>
        </div>
        {!inactive && !editing && (
          <div className="flex items-center gap-1 shrink-0 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
            {pending && (
              <button onClick={onConfirm} title="Yes, remember this" aria-label="Confirm"
                className="p-1.5 rounded-full text-green hover:bg-green/10"><Check className="h-3.5 w-3.5" /></button>
            )}
            {item.kind === 'fact' && (
              <button onClick={() => setEditing(true)} title="Correct it" aria-label="Edit"
                className="p-1.5 rounded-full text-overlay1 hover:text-text hover:bg-surface1"><Pencil className="h-3.5 w-3.5" /></button>
            )}
            <button onClick={onReject} title="Wrong, forget it" aria-label="Wrong"
              className="p-1.5 rounded-full text-overlay1 hover:text-red hover:bg-red/10"><X className="h-3.5 w-3.5" /></button>
          </div>
        )}
      </div>
    </li>
  )
}

export function LearnedFeed() {
  const { items, counts, filter, setFilter, loading, error, act, edit } = useLearned()

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto px-4 sm:px-6 py-4">
        <p className="text-xs text-overlay1 mb-3">
          What Mayday picked up from your conversations, with your exact words as evidence.
          Mark anything wrong and it is forgotten; things it wasn't sure about wait here for you.
        </p>
        <div className="flex items-center gap-1.5 mb-4">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-3 py-1 text-xs rounded-full transition-colors ${filter === f.key ? 'bg-green/15 text-green' : 'text-overlay1 hover:text-text hover:bg-surface0'}`}
            >
              {f.label}
              {f.key === 'pending' && counts.pending > 0 && (
                <span className="ml-1.5 px-1.5 rounded-full bg-yellow/20 text-yellow">{counts.pending}</span>
              )}
              {f.key === 'active' && <span className="ml-1.5 text-overlay0">{counts.active}</span>}
            </button>
          ))}
        </div>

        {error && <p className="text-sm text-red">{error}</p>}
        {!error && !loading && items.length === 0 && (
          <div className="text-center py-12">
            <Sparkles className="h-8 w-8 text-overlay0 mx-auto mb-2" />
            <p className="text-sm text-overlay1">
              {filter === 'pending' ? 'Nothing waiting for you.' : 'Nothing learned yet. Tell Mayday about your day, people, plans and ideas.'}
            </p>
          </div>
        )}
        <ul className="space-y-2">
          {items.map((it) => (
            <Row
              key={`${it.kind}:${it.id}`}
              item={it}
              onConfirm={() => act(it, 'confirm')}
              onReject={() => act(it, 'reject')}
              onEdit={(v) => edit(it, v)}
            />
          ))}
        </ul>
      </div>
    </div>
  )
}
