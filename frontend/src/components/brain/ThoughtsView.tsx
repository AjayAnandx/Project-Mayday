import { useCallback, useEffect, useState } from 'react'
import { Undo2, Eye, EyeOff, Clock, Inbox, Ban, Zap, Wand2, RefreshCw } from 'lucide-react'
import { PrepAndFriction } from './PrepAndFriction'
import { GoalsAndState } from './GoalsAndState'

interface Thought {
  id: string; ts: string; type: string; text: string; why: string; decision: string; reason: string
}
interface Action {
  id: string; ts: string; mode: string; type: string; why: string; outcome: string; undone_at: string | null
}
interface Settings { dial: string; dials: string[]; budget: number; shown_today: number; quiet_hours: string; preauthorized: string[] }

const DECISION: Record<string, { label: string; icon: typeof Eye; cls: string }> = {
  deliver: { label: 'shown', icon: Eye, cls: 'text-green' },
  autonomous: { label: 'done for you', icon: Zap, cls: 'text-green' },
  prepare: { label: 'prepared quietly', icon: Wand2, cls: 'text-blue-400' },
  defer: { label: 'waiting for a better moment', icon: Clock, cls: 'text-yellow' },
  digest: { label: 'saved for the morning digest', icon: Inbox, cls: 'text-overlay1' },
  digested: { label: 'in the digest', icon: Inbox, cls: 'text-overlay1' },
  thought: { label: 'kept to myself', icon: EyeOff, cls: 'text-overlay0' },
  rejected_unexplained: { label: "dropped: couldn't explain why", icon: Ban, cls: 'text-red' },
}
const DIAL_HELP: Record<string, string> = {
  off: 'Never speaks first (still learns)', quiet: '1 suggestion a day', balanced: '3 a day', eager: '6 a day',
}

function when(iso: string) {
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function ThoughtsView() {
  const [thoughts, setThoughts] = useState<Thought[]>([])
  const [actions, setActions] = useState<Action[]>([])
  const [settings, setSettings] = useState<Settings | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [t, a, s] = await Promise.all([
        fetch('/api/brain/thoughts?limit=60').then(r => r.json()),
        fetch('/api/brain/actions?limit=20').then(r => r.json()),
        fetch('/api/brain/proactive').then(r => r.json()),
      ])
      setThoughts(t.thoughts ?? []); setActions(a.actions ?? []); setSettings(s); setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])
  useEffect(() => { load() }, [load])

  const setDial = async (dial: string) => {
    const r = await fetch('/api/brain/proactive', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dial }) })
    if (r.ok) setSettings(await r.json())
  }
  const undo = async (id: string) => {
    await fetch(`/api/brain/actions/${id}/undo`, { method: 'POST' })
    window.dispatchEvent(new CustomEvent('planner-changed'))
    load()
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto px-4 sm:px-6 py-4 space-y-6">
        <p className="text-xs text-overlay1">
          Everything Mayday noticed and considered, what it did on its own, and what it chose not to say. Nothing here is hidden from you.
        </p>

        {settings && (
          <section aria-labelledby="dial-h">
            <h3 id="dial-h" className="text-xs font-semibold text-subtext1 mb-2">How proactive should Mayday be?</h3>
            <div className="flex flex-wrap gap-1.5" role="radiogroup">
              {settings.dials.map(d => (
                <button key={d} role="radio" aria-checked={settings.dial === d} onClick={() => setDial(d)}
                  className={`px-3 py-1.5 rounded-full text-xs transition-colors ${settings.dial === d ? 'bg-green/15 text-green' : 'bg-surface0 text-overlay1 hover:text-text'}`}>
                  <span className="capitalize">{d}</span>
                  <span className="ml-1.5 text-[10px] opacity-70">{DIAL_HELP[d]}</span>
                </button>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-overlay0">
              Today: {settings.shown_today} of {settings.budget} · quiet hours {settings.quiet_hours} · can act on its own for: {settings.preauthorized.join(', ').replace(/_/g, ' ') || 'nothing'}
            </p>
          </section>
        )}

        <GoalsAndState />

        <PrepAndFriction />

        <section aria-labelledby="did-h">
          <div className="flex items-center justify-between mb-2">
            <h3 id="did-h" className="text-xs font-semibold text-subtext1">What Mayday did</h3>
            <button onClick={load} className="text-overlay1 hover:text-text p-1" aria-label="Refresh"><RefreshCw className="h-3.5 w-3.5" /></button>
          </div>
          {actions.length === 0 ? <p className="text-xs text-overlay0">Nothing yet.</p> : (
            <ul className="space-y-1.5">
              {actions.map(a => (
                <li key={a.id} className={`rounded-xl border border-surface1 bg-surface0/60 px-3 py-2 ${a.undone_at ? 'opacity-50' : ''}`}>
                  <div className="flex items-start gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-text">{a.type.replace(/_/g, ' ')} <span className="text-[11px] text-overlay0">· {a.mode.replace('_', ' ')} · {when(a.ts)}</span></p>
                      <p className="text-[11px] text-overlay1 italic mt-0.5">{a.why}</p>
                    </div>
                    {!a.undone_at ? (
                      <button onClick={() => undo(a.id)} className="flex items-center gap-1 text-[11px] text-overlay1 hover:text-red px-2 py-1 rounded-lg hover:bg-red/10">
                        <Undo2 className="h-3 w-3" /> Undo
                      </button>
                    ) : <span className="text-[11px] text-overlay0">undone</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="th-h">
          <h3 id="th-h" className="text-xs font-semibold text-subtext1 mb-2">What Mayday considered</h3>
          {error && <p className="text-sm text-red">{error}</p>}
          {thoughts.length === 0 ? <p className="text-xs text-overlay0">Nothing yet. Thoughts appear at natural breaks and as your day changes.</p> : (
            <ul className="space-y-1.5">
              {thoughts.map(t => {
                const d = DECISION[t.decision] ?? { label: t.decision, icon: Eye, cls: 'text-overlay1' }
                const Icon = d.icon
                return (
                  <li key={t.id} className="rounded-xl border border-surface1 bg-surface0/40 px-3 py-2">
                    <p className="text-sm text-text">{t.text}</p>
                    {t.why && <p className="text-[11px] text-overlay1 italic mt-0.5">{t.why}</p>}
                    <p className={`mt-1 flex items-center gap-1 text-[11px] ${d.cls}`}>
                      <Icon className="h-3 w-3" /> {d.label}{t.reason ? ` — ${t.reason}` : ''}
                      <span className="text-overlay0 ml-1">· {when(t.ts)}</span>
                    </p>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
