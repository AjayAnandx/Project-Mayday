import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { cn } from '../../lib/utils'
import { DashCard, CardHeader, NoteBox } from './DashCard'
import type { DashboardAnalytics } from '../../types/dashboard'

const ROWS = 10

function BarStack({ value, color }: { value: number; color: 'green' | 'red' }) {
  const filled = Math.round((value / 100) * ROWS)
  return (
    <div className="flex flex-col gap-1">
      {Array.from({ length: ROWS }, (_, i) => {
        const on = ROWS - i <= filled
        return (
          <div
            key={i}
            className={cn(
              'h-2 rounded-sm',
              on ? (color === 'green' ? 'bg-green' : 'bg-red') : 'bg-hatch',
            )}
          />
        )
      })}
    </div>
  )
}

export function TaskHealth({ analytics, className }: { analytics: DashboardAnalytics; className?: string }) {
  const { total, completed, overdue } = analytics.todos
  const open = total - completed
  const completion = total ? Math.round((completed / total) * 100) : 0
  const overduePct = open ? Math.round((overdue / open) * 100) : 0
  const warn = overduePct >= 30

  return (
    <DashCard className={className}>
      <CardHeader title="Task Health" />
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <p className="text-3xl font-medium text-text tabular-nums">{completion}</p>
          <p className="text-[11px] text-overlay1 mb-3">Completed %</p>
          <BarStack value={completion} color="green" />
        </div>
        <div>
          <p className="text-3xl font-medium text-text tabular-nums">{overduePct}</p>
          <p className="text-[11px] text-overlay1 mb-3">Overdue %</p>
          <BarStack value={overduePct} color="red" />
        </div>
      </div>
      <NoteBox icon={warn ? AlertTriangle : CheckCircle2} label={warn ? 'Warning' : 'On track'}>
        {total === 0
          ? 'No tasks yet — ask Mayday to add one.'
          : warn
            ? `${overdue} of ${open} open task${open === 1 ? ' is' : 's are'} past due. Reschedule or close them out.`
            : `${completed} of ${total} tasks done, ${overdue} overdue.`}
      </NoteBox>
    </DashCard>
  )
}
