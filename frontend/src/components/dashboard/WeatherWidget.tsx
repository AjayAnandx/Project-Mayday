import { CloudSun, Droplets, Wind, MapPin, Thermometer } from 'lucide-react'
import type { DashboardWeather } from '../../types/dashboard'
import { DashCard, CardHeader } from './DashCard'

const EMOJI = /(☀️|🌤️|⛅|☁️|🌫️|🌦️|🌧️|🌨️|❄️|⛈️)/

function parse(raw: string) {
  const lines = raw.split('\n').map(l => l.trim()).filter(Boolean)
  const cur = lines.find(l => l.startsWith('Current:')) ?? ''
  const temp = cur.match(/Temperature: ([\d.-]+)°C/)?.[1]
  const condition = cur.match(/°C,\s*([^,]+?),/)?.[1]?.trim()
  const humidity = cur.match(/Humidity: (\d+)%/)?.[1]
  const wind = cur.match(/Wind: ([\d.]+) km\/h/)?.[1]
  const icon = cur.match(EMOJI)?.[1] ?? '🌤️'
  const range = lines.find(l => /^\d{4}-\d{2}-\d{2}:/.test(l))?.match(/(-?\d+)-(-?\d+)°C/)
  return { temp, condition, humidity, wind, icon, lo: range?.[1], hi: range?.[2] }
}

function Stat({ icon: Icon, label, value }: { icon: typeof Wind; label: string; value?: string }) {
  return (
    <div className="rounded-xl bg-white/[0.03] border border-white/[0.05] px-2.5 py-2">
      <p className="flex items-center gap-1 text-[10px] text-overlay1"><Icon className="h-3 w-3" />{label}</p>
      <p className="text-sm text-text tabular-nums mt-0.5">{value ?? '--'}</p>
    </div>
  )
}

export function WeatherWidget({ weather, className }: { weather: DashboardWeather | null; className?: string }) {
  if (!weather || !weather.available) {
    return (
      <DashCard className={className}>
        <CardHeader title="Weather" icon={CloudSun} />
        <div className="flex-1 rounded-2xl bg-hatch border border-white/[0.04] flex items-center justify-center py-8 px-4 text-center">
          <p className="text-xs text-overlay1">{weather?.message || 'Set your location to see weather'}</p>
        </div>
      </DashCard>
    )
  }

  const w = parse(weather.raw || '')

  return (
    <DashCard className={className}>
      <CardHeader
        title="Weather"
        icon={CloudSun}
        right={
          <span className="flex items-center gap-1 text-[11px] text-overlay1">
            <MapPin className="h-3 w-3" />{weather.location}
          </span>
        }
      />
      <div className="flex items-end justify-between gap-2">
        <div>
          <p className="text-[44px] leading-none font-medium tracking-tight text-text tabular-nums">
            {w.temp ?? '--'}<span className="text-2xl text-overlay2 align-top">°C</span>
          </p>
          {w.condition && (
            <span className="inline-block mt-3 rounded-md bg-white/10 px-1.5 py-0.5 text-[11px] font-semibold text-subtext1">
              {w.condition}
            </span>
          )}
        </div>
        <span className="text-5xl drop-shadow-[0_0_18px_rgba(250,204,21,0.35)]" aria-hidden>{w.icon}</span>
      </div>
      <div className="grid grid-cols-3 gap-2 mt-auto pt-5">
        <Stat icon={Thermometer} label="Range" value={w.lo && w.hi ? `${w.lo}–${w.hi}°` : undefined} />
        <Stat icon={Droplets} label="Humidity" value={w.humidity ? `${w.humidity}%` : undefined} />
        <Stat icon={Wind} label="Wind" value={w.wind ? `${w.wind} km/h` : undefined} />
      </div>
    </DashCard>
  )
}
