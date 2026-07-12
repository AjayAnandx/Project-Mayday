import { History, Plus, Pencil, Trash2, RefreshCw } from 'lucide-react'
import type { DashboardOperation } from '../../types/dashboard'

interface RecentActivityProps {
  operations: DashboardOperation[]
}

const actionConfig: Record<string, { icon: typeof Plus; color: string; bg: string }> = {
  create: { icon: Plus, color: 'text-green', bg: 'bg-green/15' },
  update: { icon: Pencil, color: 'text-blue-400', bg: 'bg-blue-400/15' },
  delete: { icon: Trash2, color: 'text-red', bg: 'bg-red/15' },
}

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function RecentActivity({ operations }: RecentActivityProps) {
  if (operations.length === 0) {
    return (
      <div className="rounded-xl bg-surface0/40 border border-surface1/50 p-4 sm:p-5">
        <div className="flex items-center gap-2 mb-3">
          <History className="h-4 w-4 text-green" />
          <h3 className="text-sm font-semibold text-text">Recent Activity</h3>
        </div>
        <p className="text-xs text-overlay0">No recent activity</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl bg-surface0/40 border border-surface1/50 p-4 sm:p-5">
      <div className="flex items-center gap-2 mb-3">
        <History className="h-4 w-4 text-green" />
        <h3 className="text-sm font-semibold text-text">Recent Activity</h3>
      </div>
      <div className="space-y-1">
        {operations.map((op) => {
          const cfg = actionConfig[op.action] || { icon: RefreshCw, color: 'text-overlay0', bg: 'bg-surface0/50' }
          const Icon = cfg.icon
          return (
            <div key={op.id} className="flex items-center gap-2.5 p-1.5 rounded-lg hover:bg-surface1/30 transition-colors">
              <div className={`w-6 h-6 rounded-md ${cfg.bg} flex items-center justify-center shrink-0`}>
                <Icon className={`h-3 w-3 ${cfg.color}`} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs text-text truncate">
                  <span className="font-medium capitalize">{op.action}</span>
                  {' '}
                  <span className="text-overlay0">{op.entity_type}</span>
                  {' '}
                  &lsquo;{op.entity_name}&rsquo;
                </p>
              </div>
              <span className="text-[10px] text-overlay0 shrink-0">{timeAgo(op.timestamp)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
