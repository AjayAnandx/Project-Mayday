import { Sparkles } from 'lucide-react'
import { cn } from '../../lib/utils'
import { DashCard, CardHeader, NoteBox } from './DashCard'
import type { DashboardAnalytics } from '../../types/dashboard'

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const SLOTS = ['12am', '4am', '8am', '12pm', '4pm', '8pm'] // bucket index 0..5

function level(v: number, max: number) {
  if (!v || !max) return 0
  const r = v / max
  return r > 0.66 ? 3 : r > 0.33 ? 2 : 1
}

const CELL = ['bg-hatch', 'bg-green/25', 'bg-green/55', 'bg-green shadow-[0_0_12px_rgba(34,197,94,0.35)]']

export function ActivityHeatmap({ analytics, className }: { analytics: DashboardAnalytics; className?: string }) {
  const { heatmap, day_parts } = analytics
  const max = Math.max(0, ...heatmap.flat())
  const parts = day_parts.morning + day_parts.afternoon + day_parts.evening
  const pct = (n: number) => (parts ? Math.round((n / parts) * 100) : 0)

  let peak: { b: number; d: number } | null = null
  heatmap.forEach((row, b) => row.forEach((v, d) => {
    if (v > 0 && (!peak || v > heatmap[peak.b][peak.d])) peak = { b, d }
  }))
  const p = peak as { b: number; d: number } | null

  const segs = [
    { label: 'Morning', value: pct(day_parts.morning), cls: 'bg-green' },
    { label: 'Afternoon', value: pct(day_parts.afternoon), cls: 'bg-green/45' },
    { label: 'Evening', value: pct(day_parts.evening), cls: 'bg-surface2' },
  ]

  return (
    <DashCard className={className}>
      <CardHeader title="Activity Heatmap" />

      <div className="flex items-center gap-3 text-[10px] text-overlay1 mb-4">
        {['Low', 'Medium', 'High'].map((l, i) => (
          <span key={l} className="flex items-center gap-1.5">
            <span className={cn('w-2.5 h-2.5 rounded-[3px]', CELL[i + 1].split(' ')[0])} />
            {l}
          </span>
        ))}
      </div>

      <div className="grid grid-cols-[auto_repeat(7,minmax(0,1fr))] gap-1.5 items-center">
        {[...SLOTS.keys()].reverse().map(b => (
          <div key={b} className="contents">
            <span className="text-[10px] text-overlay1 pr-1 text-right">{SLOTS[b]}</span>
            {DAYS.map((day, d) => (
              <div
                key={day}
                title={`${day} ${SLOTS[b]}–${SLOTS[(b + 1) % 6]}: ${heatmap[b][d]} actions`}
                className={cn('h-6 rounded-md transition-colors', CELL[level(heatmap[b][d], max)])}
              />
            ))}
          </div>
        ))}
        <span />
        {DAYS.map(d => (
          <span key={d} className="text-[10px] text-overlay1 text-center pt-1">{d}</span>
        ))}
      </div>

      <div className="flex h-1.5 rounded-full overflow-hidden gap-0.5 mt-5 bg-surface1">
        {segs.map(s => s.value > 0 && (
          <div key={s.label} className={s.cls} style={{ width: `${s.value}%` }} />
        ))}
      </div>
      <div className="grid grid-cols-3 mt-3 mb-4">
        {segs.map(s => (
          <div key={s.label}>
            <p className="text-xl font-medium text-text tabular-nums">{s.value}%</p>
            <p className="text-[11px] text-overlay1">{s.label}</p>
          </div>
        ))}
      </div>

      <NoteBox icon={Sparkles} label="Pattern">
        {p
          ? <>You're most active on <span className="text-subtext1">{DAYS[p.d]}s, {SLOTS[p.b]}–{SLOTS[(p.b + 1) % 6]}</span>. Schedule focused work there.</>
          : 'Not enough activity yet to spot a pattern.'}
      </NoteBox>
    </DashCard>
  )
}
