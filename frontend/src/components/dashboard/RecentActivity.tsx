import { History } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { DashboardOperation } from '../../types/dashboard'
import { DashCard, CardHeader } from './DashCard'

const ACTION: Record<string, { label: string; pill: string; dot: string }> = {
  create: { label: 'Created', pill: 'bg-green text-black', dot: 'bg-green' },
  update: { label: 'Updated', pill: 'bg-white/10 text-subtext1', dot: 'bg-subtext0' },
  delete: { label: 'Deleted', pill: 'bg-red text-white', dot: 'bg-red' },
}

function timeAgo(ts: string): string {
  const mins = Math.floor((Date.now() - new Date(ts).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export function RecentActivity({ operations, onOpen, className }: {
  operations: DashboardOperation[]
  onOpen?: () => void
  className?: string
}) {
  return (
    <DashCard className={className}>
      <CardHeader title="Recent Activity" icon={History} onOpen={onOpen} />
      {operations.length === 0 ? (
        <div className="flex-1 rounded-2xl bg-hatch border border-white/[0.04] flex items-center justify-center py-8 text-xs text-overlay1">
          No recent activity
        </div>
      ) : (
        <ol className="relative">
          {/* timeline rail */}
          <span className="absolute left-[5px] top-2 bottom-2 w-px bg-white/[0.08]" aria-hidden />
          {operations.map(op => {
            const a = ACTION[op.action] ?? { label: op.action, pill: 'bg-white/10 text-subtext1', dot: 'bg-overlay1' }
            return (
              <li key={op.id} className="relative flex items-start gap-3 py-2 pl-5">
                <span className={cn('absolute left-0 top-[13px] w-[11px] h-[11px] rounded-full border-2 border-[#0b0b0b]', a.dot)} />
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] text-text truncate">{op.entity_name || "(untitled)"}</p>
                  <p className="flex items-center gap-1.5 mt-1">
                    <span className={cn('rounded-md px-1.5 py-0.5 text-[10px] font-semibold', a.pill)}>{a.label}</span>
                    <span className="text-[10px] text-overlay1 capitalize">{op.entity_type}</span>
                  </p>
                </div>
                <span className="text-[10px] text-overlay1 shrink-0 pt-0.5 tabular-nums">{timeAgo(op.timestamp)}</span>
              </li>
            )
          })}
        </ol>
      )}
    </DashCard>
  )
}
