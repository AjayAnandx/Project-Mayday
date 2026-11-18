import { Lightbulb } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { DashboardAnalytics } from '../../types/dashboard'

function buildInsight(a: DashboardAnalytics): { pre: string; hl: string; post: string } {
  const { total, completed, overdue } = a.todos
  if (overdue > 0 && total > 0) {
    const target = Math.round(((completed + overdue) / total) * 100)
    return { pre: 'Clear', hl: `${overdue} overdue`, post: `task${overdue === 1 ? '' : 's'} to lift completion to ${target}%.` }
  }
  if (a.prev_total > 0) {
    const d = Math.round(((a.total - a.prev_total) / a.prev_total) * 100)
    return d >= 0
      ? { pre: 'Activity is up', hl: `${d}%`, post: 'versus the previous 30 days. Keep the streak going.' }
      : { pre: 'Activity dipped', hl: `${Math.abs(d)}%`, post: 'versus the previous 30 days. Time for a quick review?' }
  }
  return { pre: 'Mayday logged', hl: `${a.total}`, post: 'actions in the last 30 days.' }
}

export function InsightCard({ analytics, className }: { analytics: DashboardAnalytics; className?: string }) {
  const { pre, hl, post } = buildInsight(analytics)
  const { total, completed } = analytics.todos
  const filled = total ? Math.round((completed / total) * 10) : 0

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-[20px] p-5 flex flex-col justify-between min-h-[200px]',
        'bg-gradient-to-br from-[#16a34a] via-[#15803d] to-[#052e16] border border-green/40',
        className,
      )}
    >
      {/* sparkles */}
      <span className="absolute top-6 right-8 w-1 h-1 rounded-full bg-white/90 shadow-[0_0_8px_2px_rgba(255,255,255,0.6)]" />
      <span className="absolute top-12 right-14 w-0.5 h-0.5 rounded-full bg-white/70" />
      <span className="absolute top-16 right-6 w-1.5 h-1.5 rounded-full bg-white/80 shadow-[0_0_10px_3px_rgba(255,255,255,0.5)]" />
      <span className="absolute top-9 right-20 w-0.5 h-0.5 rounded-full bg-white/60" />

      <span className="self-start inline-flex items-center gap-1.5 rounded-full bg-white/15 border border-white/20 px-2.5 py-1 text-[11px] text-white">
        <Lightbulb className="h-3 w-3" /> Insight
      </span>

      <p className="text-xl leading-snug text-white mt-6">
        {pre}{' '}
        <span className="inline-block rounded-lg bg-white text-[#14532d] font-semibold px-1.5 leading-tight">{hl}</span>{' '}
        {post}
      </p>

      <div className="flex gap-1 mt-5" aria-label={`Task completion ${filled * 10}%`}>
        {Array.from({ length: 10 }, (_, i) => (
          <div key={i} className={cn('h-3 flex-1 rounded-[4px]', i < filled ? 'bg-white' : 'bg-white/15')} />
        ))}
      </div>
    </div>
  )
}
