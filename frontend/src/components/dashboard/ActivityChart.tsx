import { useEffect, useMemo, useRef, useState } from 'react'
import { DashCard, CardHeader, compact } from './DashCard'

interface Point { date: string; count: number }

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [w, setW] = useState(0)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

function niceMax(v: number) {
  if (v <= 4) return 4
  const mag = 10 ** Math.floor(Math.log10(v))
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * mag >= v) return m * mag
  return 10 * mag
}

/** Catmull-Rom → cubic Bézier for a smooth line through every point. */
function smooth(pts: [number, number][]) {
  if (pts.length < 2) return ''
  let d = `M${pts[0][0]},${pts[0][1]}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] ?? p2
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6]
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6]
    d += ` C${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${p2[0]},${p2[1]}`
  }
  return d
}

const H = 230
const PAD = { l: 36, r: 8, t: 34, b: 28 }

export function ActivityChart({ daily, className }: { daily: Point[]; className?: string }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const peakIdx = useMemo(
    () => daily.reduce((best, p, i) => (p.count > daily[best].count ? i : best), 0),
    [daily],
  )
  const [hover, setHover] = useState<number | null>(null)
  const active = hover ?? peakIdx

  const max = niceMax(Math.max(0, ...daily.map(d => d.count)))
  const innerW = Math.max(0, width - PAD.l - PAD.r)
  const innerH = H - PAD.t - PAD.b
  const step = daily.length > 1 ? innerW / (daily.length - 1) : 0
  const x = (i: number) => PAD.l + i * step
  const y = (v: number) => PAD.t + innerH - (v / max) * innerH
  const pts = daily.map((d, i) => [x(i), y(d.count)] as [number, number])
  const line = smooth(pts)
  const area = line && `${line} L${x(daily.length - 1)},${PAD.t + innerH} L${x(0)},${PAD.t + innerH} Z`
  const ticks = [0, 1, 2, 3, 4, 5].map(i => (max / 5) * i)

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!step) return
    const rect = e.currentTarget.getBoundingClientRect()
    const i = Math.round((e.clientX - rect.left - PAD.l) / step)
    setHover(Math.min(daily.length - 1, Math.max(0, i)))
  }

  const a = daily[active]
  const ax = x(active)
  const ay = a ? y(a.count) : 0

  return (
    <DashCard className={className}>
      <CardHeader title="Daily Activity" right={<span className="text-[11px] text-overlay1">last 30 days</span>} />
      <div ref={ref} className="relative flex-1 min-h-[230px]">
        {width > 0 && daily.length > 1 && (
          <svg width={width} height={H} onMouseMove={onMove} onMouseLeave={() => setHover(null)} className="block">
            <defs>
              <pattern id="ac-grid" width="14" height="14" patternUnits="userSpaceOnUse">
                <path d="M14 0H0V14" fill="none" stroke="rgba(34,197,94,0.22)" strokeWidth="1" />
              </pattern>
              <linearGradient id="ac-fade" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="white" stopOpacity="0.9" />
                <stop offset="1" stopColor="white" stopOpacity="0.05" />
              </linearGradient>
              <mask id="ac-mask"><path d={area} fill="url(#ac-fade)" /></mask>
              <linearGradient id="ac-pill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#e5e5e5" stopOpacity="0.9" />
                <stop offset="1" stopColor="#e5e5e5" stopOpacity="0.05" />
              </linearGradient>
              <filter id="ac-glow" x="-10%" y="-30%" width="120%" height="160%">
                <feGaussianBlur stdDeviation="4" result="b" />
                <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
            </defs>

            {ticks.map(t => (
              <g key={t}>
                <text x={0} y={y(t) + 3} fontSize="10" fill="#737373">{compact(Math.round(t))}</text>
              </g>
            ))}

            <rect x={PAD.l} y={PAD.t} width={innerW} height={innerH} fill="url(#ac-grid)" mask="url(#ac-mask)" />

            {/* hover/peak highlight pill */}
            {a && (
              <rect x={ax - 11} y={ay - 6} width={22} height={PAD.t + innerH - ay + 6} rx={11} fill="url(#ac-pill)" opacity={0.55} />
            )}

            <path d={line} fill="none" stroke="#e5e5e5" strokeWidth="2" filter="url(#ac-glow)" />

            {a && (
              <>
                <circle cx={ax} cy={ay} r={3.5} fill="#050505" stroke="#e5e5e5" strokeWidth="1.5" />
                <g transform={`translate(${Math.min(width - 30, Math.max(30, ax))}, ${Math.max(12, ay - 22)})`}>
                  <rect x={-26} y={-12} width={52} height={22} rx={8} fill="#050505" stroke="rgba(255,255,255,0.25)" />
                  <text textAnchor="middle" y={3} fontSize="11" fontWeight="600" fill="#e5e5e5">{compact(a.count)}</text>
                </g>
              </>
            )}

            {daily.map((d, i) => i % 2 === active % 2 && (
              <g key={d.date}>
                {i === active && <circle cx={x(i)} cy={H - 10} r={10} fill="none" stroke="rgba(255,255,255,0.35)" />}
                <text x={x(i)} y={H - 6} textAnchor="middle" fontSize="10" fill={i === active ? '#e5e5e5' : '#737373'}>
                  {Number(d.date.slice(8, 10))}
                </text>
              </g>
            ))}
          </svg>
        )}
      </div>
    </DashCard>
  )
}
