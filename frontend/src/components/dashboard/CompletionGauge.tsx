import { DashCard, CardHeader } from './DashCard'

const SEGMENTS = 22
const CX = 120
const CY = 118
const R_OUT = 108
const R_IN = 74

export function CompletionGauge({ value, label, onOpen, className }: {
  value: number
  label: string
  onOpen?: () => void
  className?: string
}) {
  const filled = Math.round((value / 100) * SEGMENTS)
  const step = Math.PI / SEGMENTS
  const pad = step * 0.22

  const segs = Array.from({ length: SEGMENTS }, (_, i) => {
    const a0 = Math.PI + i * step + pad / 2
    const a1 = a0 + step - pad
    const p = (r: number, a: number) => `${CX + r * Math.cos(a)},${CY + r * Math.sin(a)}`
    return {
      d: `M${p(R_IN, a0)} L${p(R_OUT, a0)} A${R_OUT},${R_OUT} 0 0 1 ${p(R_OUT, a1)} L${p(R_IN, a1)} A${R_IN},${R_IN} 0 0 0 ${p(R_IN, a0)} Z`,
      on: i < filled,
      // fade filled segments slightly toward the leading edge
      opacity: i < filled ? 0.55 + 0.45 * (i / Math.max(1, filled - 1)) : 1,
    }
  })

  return (
    <DashCard className={className}>
      <CardHeader title="Completion Score" onOpen={onOpen} />
      <div className="flex-1 flex items-center justify-center">
        <svg viewBox="0 0 240 130" className="w-full max-w-[300px]">
          {segs.map((s, i) => (
            <path
              key={i}
              d={s.d}
              fill={s.on ? '#22c55e' : '#1f1f1f'}
              fillOpacity={s.opacity}
              stroke={s.on ? 'none' : '#2a2a2a'}
              strokeLinejoin="round"
            />
          ))}
          <text x={CX} y={CY - 14} textAnchor="middle" fontSize="34" fontWeight="500" fill="#e5e5e5">{value}%</text>
          <text x={CX} y={CY + 6} textAnchor="middle" fontSize="11" fill="#737373">{label}</text>
        </svg>
      </div>
    </DashCard>
  )
}
