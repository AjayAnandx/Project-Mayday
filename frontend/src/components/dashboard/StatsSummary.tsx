import { ListTodo, CalendarDays, MessageSquare, Briefcase } from 'lucide-react'
import type { DashboardStats } from '../../types/dashboard'

interface StatsSummaryProps {
  stats: DashboardStats
}

const cards = [
  { key: 'open_todos', icon: ListTodo, label: 'Open Tasks', color: 'text-green', bg: 'bg-green/15' },
  { key: 'today_events', icon: CalendarDays, label: "Today's Events", color: 'text-blue-400', bg: 'bg-blue-400/15' },
  { key: 'active_projects', icon: Briefcase, label: 'Active Projects', color: 'text-amber-400', bg: 'bg-amber-400/15' },
  { key: 'total_conversations', icon: MessageSquare, label: 'Conversations', color: 'text-purple-400', bg: 'bg-purple-400/15' },
] as const

export function StatsSummary({ stats }: StatsSummaryProps) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {cards.map(({ key, icon: Icon, label, color, bg }) => (
        <div key={key} className="rounded-xl bg-surface0/40 border border-surface1/50 p-3 sm:p-4 flex items-center gap-3">
          <div className={`w-9 h-9 rounded-lg ${bg} flex items-center justify-center shrink-0`}>
            <Icon className={`h-4 w-4 ${color}`} />
          </div>
          <div className="min-w-0">
            <p className="text-lg sm:text-xl font-bold text-text">{stats[key] as number}</p>
            <p className="text-[11px] text-overlay0 truncate">{label}</p>
          </div>
        </div>
      ))}
    </div>
  )
}
