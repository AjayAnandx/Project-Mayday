import { useEffect, useState } from 'react'
import { Mail, Phone, Trash2, UserPlus } from 'lucide-react'
import { cn } from '../../lib/utils'
import { api } from '../../services/api'
import { usePlannerActions, usePlannerVersion } from '../../hooks/usePlanner'
import { ItemRow } from './ItemRow'
import type { Person, PersonDetail, PlannerItem } from '../../types/planner'

const field = 'w-full rounded-xl bg-white/[0.04] border border-white/[0.08] px-3 py-2 text-sm text-text placeholder:text-overlay0 focus:outline-none focus:border-green/50'

/** People directory + a two-way ledger: what they owe you / what you owe them. */
export function PeopleView({ people, onOpen }: { people: Person[]; onOpen: (i: PlannerItem) => void }) {
  const actions = usePlannerActions()
  const version = usePlannerVersion()
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<PersonDetail | null>(null)
  const [form, setForm] = useState({ name: '', email: '', relation: '' })
  const [edit, setEdit] = useState<Partial<Person>>({})

  useEffect(() => {
    if (!selected && people.length) setSelected(people[0].id)
  }, [people, selected])

  useEffect(() => {
    if (!selected) { setDetail(null); return }
    let cancelled = false
    api.planner.person(selected).then(d => { if (!cancelled) { setDetail(d); setEdit({ email: d.email, phone: d.phone, relation: d.relation, notes: d.notes }) } })
      .catch(() => { if (!cancelled) setDetail(null) })
    return () => { cancelled = true }
  }, [selected, version])

  const add = async () => {
    if (!form.name.trim()) return
    const p = await actions.createPerson({ name: form.name.trim(), email: form.email.trim(), relation: form.relation.trim() })
    setForm({ name: '', email: '', relation: '' })
    setSelected(p.id)
  }

  return (
    <div className="grid gap-3 lg:grid-cols-[280px_1fr] min-h-0">
      <div className="rounded-[20px] bg-[#0b0b0b] border border-white/[0.06] p-3 flex flex-col gap-3">
        <div className="space-y-2">
          <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Name" aria-label="New person name" className={field}
                 onKeyDown={e => { if (e.key === 'Enter') add() }} />
          <div className="flex gap-2">
            <input value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} placeholder="Email (for follow-ups)" aria-label="Email" className={field} />
          </div>
          <button onClick={add} className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-green text-black text-xs font-semibold py-2 hover:bg-green/90">
            <UserPlus className="h-3.5 w-3.5" /> Add person
          </button>
        </div>
        <ul className="space-y-1 overflow-y-auto">
          {people.length === 0 && <li className="text-[11px] text-overlay1 px-1">People appear here when you delegate something or add them.</li>}
          {people.map(p => (
            <li key={p.id}>
              <button onClick={() => setSelected(p.id)}
                      className={cn('w-full flex items-center gap-2.5 rounded-xl px-2 py-2 text-left transition-colors',
                        selected === p.id ? 'bg-white/[0.07]' : 'hover:bg-white/[0.04]')}>
                <span className="w-8 h-8 rounded-full bg-white/[0.06] flex items-center justify-center text-xs font-semibold text-subtext1">{p.name.slice(0, 1).toUpperCase()}</span>
                <span className="flex-1 min-w-0">
                  <span className="block text-sm text-text truncate">{p.name}</span>
                  <span className="block text-[10px] text-overlay1">owes {p.waiting_count ?? 0} · you owe {p.owed_count ?? 0}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {detail ? (
        <div className="rounded-[20px] bg-[#0b0b0b] border border-white/[0.06] p-5 space-y-5 min-w-0">
          <div className="flex items-start gap-4">
            <span className="w-12 h-12 rounded-full bg-gradient-to-br from-[#86efac] to-[#16a34a] flex items-center justify-center text-black text-lg font-bold">{detail.name.slice(0, 1).toUpperCase()}</span>
            <div className="flex-1 min-w-0">
              <h2 className="text-xl font-medium text-text">{detail.name}</h2>
              <div className="grid sm:grid-cols-3 gap-2 mt-3">
                <label className="flex items-center gap-2"><Mail className="h-3.5 w-3.5 text-overlay1 shrink-0" />
                  <input value={edit.email ?? ''} onChange={e => setEdit({ ...edit, email: e.target.value })} placeholder="email" aria-label="Email" className={field} /></label>
                <label className="flex items-center gap-2"><Phone className="h-3.5 w-3.5 text-overlay1 shrink-0" />
                  <input value={edit.phone ?? ''} onChange={e => setEdit({ ...edit, phone: e.target.value })} placeholder="phone" aria-label="Phone" className={field} /></label>
                <input value={edit.relation ?? ''} onChange={e => setEdit({ ...edit, relation: e.target.value })} placeholder="relation (client, family…)" aria-label="Relation" className={field} />
              </div>
              <div className="flex gap-2 mt-2">
                <button onClick={() => actions.updatePerson(detail.id, edit)} className="px-3 py-1.5 rounded-xl bg-white/[0.06] text-xs text-text hover:bg-white/[0.1]">Save details</button>
                <button onClick={async () => { if (window.confirm(`Remove ${detail.name}? Their items stay, unlinked.`)) { await actions.deletePerson(detail.id); setSelected(null) } }}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs text-red hover:bg-red/10"><Trash2 className="h-3.5 w-3.5" /> Remove</button>
              </div>
            </div>
          </div>

          {[
            { title: `They owe you (${detail.they_owe.length})`, list: detail.they_owe },
            { title: `You owe them (${detail.i_owe.length})`, list: detail.i_owe },
          ].map(sec => (
            <section key={sec.title}>
              <h3 className="text-sm text-subtext1 mb-2">{sec.title}</h3>
              {sec.list.length === 0
                ? <p className="text-[11px] text-overlay1 rounded-xl bg-hatch px-3 py-3">Nothing here.</p>
                : <div className="space-y-1.5">{sec.list.map(i => (
                    <ItemRow key={i.id} item={i} people={people} onOpen={onOpen} onComplete={it => actions.complete(it.id, it.status !== 'done')} />
                  ))}</div>}
            </section>
          ))}
        </div>
      ) : (
        <div className="rounded-[20px] bg-hatch border border-white/[0.04] flex items-center justify-center text-xs text-overlay1 py-16">Select a person</div>
      )}
    </div>
  )
}
