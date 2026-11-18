import type { ReactNode } from 'react'
import type { ArrowUpRight } from 'lucide-react'
import { DashCard, OpenButton } from './DashCard'

interface KpiCardProps {
  label: string
  icon: typeof ArrowUpRight
  value: ReactNode
  badge?: ReactNode
  onOpen?: () => void
}

export function KpiCard({ label, icon: Icon, value, badge, onOpen }: KpiCardProps) {
  return (
    <DashCard className="justify-between min-h-[136px]">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 text-sm text-subtext0 min-w-0">
          <Icon className="h-4 w-4 text-overlay2 shrink-0" />
          <span className="truncate">{label}</span>
        </div>
        {onOpen && <OpenButton onClick={onOpen} label={label} />}
      </div>
      <div className="flex items-end gap-3 mt-6">
        <span className="text-4xl sm:text-[44px] leading-none font-medium tracking-tight text-text tabular-nums">
          {value}
        </span>
        {badge && <span className="mb-1.5">{badge}</span>}
      </div>
    </DashCard>
  )
}
