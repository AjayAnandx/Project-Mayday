import { useState } from 'react'
import { Mail, FlaskConical, Briefcase, ListTodo, CalendarDays, BrainCircuit, Sparkles } from 'lucide-react'
import { cn } from '../../lib/utils'
import { DashCard, CardHeader, NoteBox, compact } from './DashCard'
import type { ActivityMixData, DashboardAnalytics, MixGroupKey } from '../../types/dashboard'

const META: Record<MixGroupKey, { label: string; icon: typeof Mail; color: string }> = {
  email: { label: 'Email', icon: Mail, color: '#22c55e' },
  research: { label: 'Research', icon: FlaskConical, color: '#4ade80' },
  projects: { label: 'Projects', icon: Briefcase, color: '#16a34a' },
  tasks: { label: 'Tasks', icon: ListTodo, color: '#86efac' },
  calendar: { label: 'Calendar', icon: CalendarDays, color: '#15803d' },
  memory: { label: 'Memory & Docs', icon: BrainCircuit, color: '#bbf7d0' },
}

const ACTIONS = [
  { key: 'created', label: 'Created', color: '#22c55e' },
  { key: 'updated', label: 'Updated', color: '#a3a3a3' },
  { key: 'removed', label: 'Removed', color: '#ef4444' },
] as const

const SIZE = 184
const C0 = SIZE / 2

/** One ring of the donut. Zero-total rings render as a hatched track. */
function Ring({ r, width, parts }: { r: number; width: number; parts: { key: string; value: number; color: string }[] }) {
  const circ = 2 * Math.PI * r
  const total = parts.reduce((s, p) => s + p.value, 0)
  const live = parts.filter(p => p.value > 0)
  const gap = live.length > 1 ? 3 : 0
  let offset = 0
  return (
    <>
      <circle cx={C0} cy={C0} r={r} fill="none" stroke="url(#mix-hatch)" strokeWidth={width} />
      <g transform={`rotate(-90 ${C0} ${C0})`}>
        {total > 0 && live.map(p => {
          const len = (p.value / total) * circ
          const seg = (
            <circle
              key={p.key}
              cx={C0} cy={C0} r={r} fill="none"
              stroke={p.color} strokeWidth={width}
              strokeDasharray={`${Math.max(0.5, len - gap)} ${circ}`}
              strokeDashoffset={-offset}
            />
          )
          offset += len
          return seg
        })}
      </g>
    </>
  )
}

function Sparkline({ data, color, muted }: { data: number[]; color: string; muted: boolean }) {
  const w = 72, h = 20
  const max = Math.max(1, ...data)
  const step = data.length > 1 ? w / (data.length - 1) : w
  const pts = data.map((v, i) => `${(i * step).toFixed(1)},${(h - 2 - (v / max) * (h - 4)).toFixed(1)}`).join(' ')
  return (
    <svg width={w} height={h} className="shrink-0" aria-hidden>
      <polyline points={pts} fill="none" stroke={muted ? '#303030' : color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

function note(view: 'recent' | 'all', mix: ActivityMixData, all: ActivityMixData) {
  const sorted = [...mix.groups].sort((a, b) => b.count - a.count)
  const lead = sorted[0]
  if (!lead || mix.total === 0) return 'Nothing logged yet — every action Mayday takes will show up here.'
  const share = Math.round((lead.count / mix.total) * 100)
  if (view === 'recent') {
    const quiet = all.groups
      .filter(g => g.count > 0 && (mix.groups.find(r => r.key === g.key)?.count ?? 0) === 0)
      .sort((a, b) => b.count - a.count)
      .slice(0, 2)
      .map(g => META[g.key].label)
    if (quiet.length) {
      return `${META[lead.key].label} is ${share}% of this month. ${quiet.join(' and ')} — your busiest areas all-time — have been quiet for 30 days.`
    }
  }
  return `${META[lead.key].label} leads with ${share}% of ${view === 'recent' ? 'this month' : 'all activity'}.`
}

export function ActivityMix({ analytics, className }: { analytics: DashboardAnalytics; className?: string }) {
  const [view, setView] = useState<'recent' | 'all'>('recent')
  const mixes = analytics.mix
  if (!mixes) return null
  const mix = mixes[view]
  const pct = (v: number) => (mix.total ? Math.round((v / mix.total) * 100) : 0)

  return (
    <DashCard className={className}>
      <svg width="0" height="0" className="absolute">
        <defs>
          <pattern id="mix-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="#121212" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="#2c2c2c" strokeWidth="2" />
          </pattern>
        </defs>
      </svg>

      <CardHeader
        title="Activity Mix"
        right={
          <div className="flex rounded-[10px] bg-white/[0.04] border border-white/[0.06] p-0.5" role="tablist">
            {(['recent', 'all'] as const).map(v => (
              <button
                key={v}
                role="tab"
                aria-selected={view === v}
                onClick={() => setView(v)}
                className={cn(
                  'px-2.5 py-1 rounded-[8px] text-[11px] font-medium transition-colors',
                  view === v ? 'bg-text text-black' : 'text-subtext0 hover:text-text',
                )}
              >
                {v === 'recent' ? '30 days' : 'All time'}
              </button>
            ))}
          </div>
        }
      />

      <div className="grid md:grid-cols-[auto_1fr] gap-6 items-center mb-4">
        {/* Donut: outer = category, inner = action kind */}
        <div className="flex flex-col items-center gap-3">
          <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
            <Ring r={80} width={18} parts={mix.groups.map(g => ({ key: g.key, value: g.count, color: META[g.key].color }))} />
            <Ring r={60} width={6} parts={ACTIONS.map(a => ({ key: a.key, value: mix.actions[a.key], color: a.color }))} />
            <text x={C0} y={C0 + 4} textAnchor="middle" fontSize="28" fontWeight="500" fill="#e5e5e5">{compact(mix.total)}</text>
            <text x={C0} y={C0 + 22} textAnchor="middle" fontSize="11" fill="#737373">Actions</text>
          </svg>
          <div className="flex gap-3 text-[10px] text-overlay1">
            {ACTIONS.map(a => (
              <span key={a.key} className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: a.color }} />
                {a.label} <span className="text-subtext1 tabular-nums">{compact(mix.actions[a.key])}</span>
              </span>
            ))}
          </div>
        </div>

        {/* Category table — all six always shown */}
        <ul className="min-w-0 divide-y divide-white/[0.04]">
          {mix.groups.map(g => {
            const m = META[g.key]
            const Icon = m.icon
            const off = g.count === 0
            return (
              <li key={g.key} className="flex items-center gap-3 py-2">
                <span
                  className={cn('w-7 h-7 rounded-lg flex items-center justify-center shrink-0', off ? 'bg-white/[0.03]' : '')}
                  style={off ? undefined : { background: `${m.color}1f` }}
                >
                  <Icon className="h-3.5 w-3.5" style={{ color: off ? '#525252' : m.color }} />
                </span>
                <span className={cn('flex-1 min-w-0 text-xs truncate', off ? 'text-overlay0' : 'text-subtext1')}>{m.label}</span>
                <span className="hidden sm:block"><Sparkline data={g.daily} color={m.color} muted={off} /></span>
                <span className={cn('w-12 text-right text-xs tabular-nums', off ? 'text-overlay0' : 'text-text')}>
                  {off ? '—' : compact(g.count)}
                </span>
                <span className="w-16 flex items-center gap-1.5">
                  <span className="flex-1 h-1 rounded-full bg-white/[0.06] overflow-hidden">
                    <span className="block h-full rounded-full" style={{ width: `${pct(g.count)}%`, background: m.color }} />
                  </span>
                  <span className={cn('w-7 text-right text-[10px] tabular-nums', off ? 'text-overlay0' : 'text-subtext0')}>{pct(g.count)}%</span>
                </span>
              </li>
            )
          })}
        </ul>
      </div>

      <NoteBox icon={Sparkles} label="Note">{note(view, mix, mixes.all)}</NoteBox>
    </DashCard>
  )
}
