/** Dependency-free SVG charts in Mayday's palette (bar, line, pie; multi-series). */
const COLORS = ['#22c55e', '#3b82f6', '#eab308', '#a855f7', '#f97316', '#14b8a6', '#ec4899', '#737373']

interface Props {
  kind: 'bar' | 'line' | 'pie'
  title: string
  labels: string[]
  series: { name: string; values: number[] }[]
  unit?: string
}

function fmt(n: number, unit?: string) {
  const abs = Math.abs(n)
  const s = abs >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : abs >= 1e6 ? `${(n / 1e6).toFixed(1)}M`
    : abs >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : Number.isInteger(n) ? `${n}` : n.toFixed(2)
  return unit ? `${s} ${unit}` : s
}

function Legend({ series }: { series: Props['series'] }) {
  if (series.length < 2) return null
  return (
    <div className="flex flex-wrap gap-3">
      {series.map((s, i) => (
        <span key={i} className="flex items-center gap-1.5 text-[11px] text-subtext0">
          <span className="h-2 w-2 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />{s.name}
        </span>
      ))}
    </div>
  )
}

function Pie({ labels, series }: Props) {
  const values = (series[0]?.values ?? []).map(v => Math.max(0, v))
  const total = values.reduce((a, b) => a + b, 0) || 1
  let angle = -Math.PI / 2
  const arcs = values.map((v, i) => {
    const a0 = angle
    angle += (v / total) * Math.PI * 2
    const large = angle - a0 > Math.PI ? 1 : 0
    const [x0, y0, x1, y1] = [Math.cos(a0), Math.sin(a0), Math.cos(angle), Math.sin(angle)].map(n => 50 + 40 * n)
    return values.length === 1
      ? <circle key={i} cx="50" cy="50" r="40" fill={COLORS[0]} />
      : <path key={i} d={`M50,50 L${x0},${y0} A40,40 0 ${large} 1 ${x1},${y1} Z`} fill={COLORS[i % COLORS.length]} />
  })
  return (
    <div className="flex flex-wrap items-center gap-4">
      <svg viewBox="0 0 100 100" className="h-40 w-40" role="img">{arcs}</svg>
      <ul className="space-y-1">
        {labels.map((l, i) => (
          <li key={i} className="flex items-center gap-2 text-xs text-subtext1">
            <span className="h-2 w-2 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
            {l} <span className="text-overlay1 tabular-nums">{((values[i] ?? 0) / total * 100).toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Cartesian({ kind, labels, series, unit }: Props) {
  const W = 600, H = 220, L = 52, B = 28, T = 8, R = 8
  const all = series.flatMap(s => s.values)
  const max = Math.max(0, ...all), min = Math.min(0, ...all)
  const span = max - min || 1
  const y = (v: number) => T + (H - T - B) * (1 - (v - min) / span)
  const n = Math.max(1, labels.length)
  const slot = (W - L - R) / n
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => min + span * f)
  const step = Math.ceil(n / 12)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img">
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="rgba(255,255,255,0.06)" />
          <text x={L - 6} y={y(t) + 3} textAnchor="end" fontSize="10" fill="#737373">{fmt(t, unit && i === 4 ? unit : undefined)}</text>
        </g>
      ))}
      {labels.map((l, i) => i % step === 0 && (
        <text key={i} x={L + slot * (i + 0.5)} y={H - 8} textAnchor="middle" fontSize="10" fill="#737373">
          {l.length > 10 ? `${l.slice(0, 9)}…` : l}
        </text>
      ))}
      {kind === 'bar' && series.map((s, si) => {
        const bw = (slot * 0.7) / series.length
        return s.values.map((v, i) => (
          <rect key={`${si}-${i}`} x={L + slot * i + slot * 0.15 + bw * si} width={Math.max(1, bw - 1)}
                y={Math.min(y(v), y(0))} height={Math.abs(y(v) - y(0))} rx="2" fill={COLORS[si % COLORS.length]}>
            <title>{`${s.name} · ${labels[i]}: ${fmt(v, unit)}`}</title>
          </rect>
        ))
      })}
      {kind === 'line' && series.map((s, si) => (
        <g key={si}>
          <polyline fill="none" stroke={COLORS[si % COLORS.length]} strokeWidth="2"
                    points={s.values.map((v, i) => `${L + slot * (i + 0.5)},${y(v)}`).join(' ')} />
          {s.values.map((v, i) => (
            <circle key={i} cx={L + slot * (i + 0.5)} cy={y(v)} r="2.5" fill={COLORS[si % COLORS.length]}>
              <title>{`${s.name} · ${labels[i]}: ${fmt(v, unit)}`}</title>
            </circle>
          ))}
        </g>
      ))}
    </svg>
  )
}

export function ChartView(props: Props) {
  return (
    <figure className="rounded-2xl border border-white/[0.06] p-3 space-y-2">
      <figcaption className="text-xs font-medium text-subtext1">{props.title}</figcaption>
      {props.kind === 'pie' ? <Pie {...props} /> : <Cartesian {...props} />}
      {props.kind !== 'pie' && <Legend series={props.series} />}
    </figure>
  )
}
