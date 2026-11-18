import type { ReactNode } from 'react'
import { ArrowUpRight } from 'lucide-react'
import { cn } from '../../lib/utils'

/** Shared surface for every dashboard tile — soft black, hairline border, 20px radius. */
export const CARD = 'rounded-[20px] bg-[#0b0b0b] border border-white/[0.06] p-5'

export function DashCard({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn(CARD, 'flex flex-col min-w-0', className)}>{children}</div>
}

export function CardHeader({
  title, icon: Icon, onOpen, right,
}: {
  title: string
  icon?: typeof ArrowUpRight
  onOpen?: () => void
  right?: ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-2 mb-4">
      <div className="flex items-center gap-2 min-w-0">
        {Icon && <Icon className="h-4 w-4 text-overlay2 shrink-0" />}
        <h3 className="text-sm text-subtext1 truncate">{title}</h3>
      </div>
      {right}
      {onOpen && <OpenButton onClick={onOpen} label={title} />}
    </div>
  )
}

export function OpenButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      aria-label={`Open ${label}`}
      className="w-8 h-8 shrink-0 rounded-full border border-white/10 flex items-center justify-center text-subtext0 hover:text-text hover:border-white/25 hover:bg-white/5 transition-colors"
    >
      <ArrowUpRight className="h-4 w-4" />
    </button>
  )
}

/** Small boxed footnote with an icon, used for "AI note" style callouts. */
export function NoteBox({ icon: Icon, label, children }: { icon: typeof ArrowUpRight; label: string; children: ReactNode }) {
  return (
    <div className="mt-auto flex gap-2.5 rounded-xl bg-white/[0.03] border border-white/[0.05] px-3 py-2.5">
      <Icon className="h-4 w-4 text-overlay2 shrink-0 mt-0.5" />
      <p className="text-[11px] leading-relaxed text-overlay2">
        <span className="font-semibold text-subtext1">{label}:</span> {children}
      </p>
    </div>
  )
}

export function DeltaPill({ value, suffix = '%', invert = false }: { value: number; suffix?: string; invert?: boolean }) {
  const good = invert ? value <= 0 : value >= 0
  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11px] font-semibold',
        good ? 'bg-green text-black' : 'bg-red text-white',
      )}
    >
      {value >= 0 ? '▲' : '▼'} {value > 0 ? '+' : ''}{value}{suffix}
    </span>
  )
}

export function compact(n: number): string {
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}m`
  if (n >= 1_000) return `${+(n / 1_000).toFixed(1)}k`
  return String(n)
}
