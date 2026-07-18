import { CloudSun, MapPin } from 'lucide-react'
import type { DashboardWeather } from '../../types/dashboard'

interface WeatherWidgetProps {
  weather: DashboardWeather | null
}

export function WeatherWidget({ weather }: WeatherWidgetProps) {
  if (!weather || !weather.available) {
    return (
      <div className="rounded-xl bg-surface0/40 border border-surface1/50 p-4 sm:p-5">
        <div className="flex items-center gap-2 mb-3">
          <CloudSun className="h-4 w-4 text-green" />
          <h3 className="text-sm font-semibold text-text">Weather</h3>
        </div>
        <p className="text-xs text-overlay0">{weather?.message || 'Set your location to see weather'}</p>
      </div>
    )
  }

  const lines = (weather.raw || '').split('\n').filter(Boolean)
  const currentLine = lines.find(l => l.startsWith('Current:'))
  const tempMatch = currentLine?.match(/Temperature: ([\d.-]+)°C/)
  const condMatch = currentLine?.match(/:\s*(.+?)\s*(?:☀️|🌤️|⛅|☁️|🌫️|🌦️|🌧️|🌨️|❄️|⛈️)/)
  const emojiMatch = currentLine?.match(/(☀️|🌤️|⛅|☁️|🌫️|🌦️|🌧️|🌨️|❄️|⛈️)/)

  const temperature = tempMatch ? `${tempMatch[1]}°C` : '--'
  const condition = condMatch ? condMatch[1].trim() : ''
  const icon = emojiMatch ? emojiMatch[1] : '🌤️'

  return (
    <div className="rounded-xl bg-surface0/40 border border-surface1/50 p-4 sm:p-5">
      <div className="flex items-center gap-2 mb-3">
        <CloudSun className="h-4 w-4 text-green" />
        <h3 className="text-sm font-semibold text-text">Weather</h3>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-3xl">{icon}</span>
        <div>
          <p className="text-xl font-bold text-text">{temperature}</p>
          {condition && <p className="text-xs text-subtext0">{condition}</p>}
          <p className="text-[11px] text-overlay0 flex items-center gap-1 mt-0.5">
            <MapPin className="h-3 w-3" />
            {weather.location}
          </p>
        </div>
      </div>
    </div>
  )
}
