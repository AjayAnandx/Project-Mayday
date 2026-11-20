import { RefreshCw, CalendarDays, ListTodo, Hourglass, ChevronDown } from 'lucide-react'
import { useChatContext } from '../../context/ChatContext'
import { useDashboard } from '../../hooks/useDashboard'
import type { Page } from '../layout/Sidebar'
import { UpcomingEvents } from './UpcomingEvents'
import { RecentActivity } from './RecentActivity'
import { WeatherWidget } from './WeatherWidget'
import { AINewsWidget } from './AINewsWidget'
import { MusicWidget } from './MusicWidget'
import { GmailBadge } from './GmailBadge'
import { KpiCard } from './KpiCard'
import { ActivityChart } from './ActivityChart'
import { ActivityHeatmap } from './ActivityHeatmap'
import { TaskHealth } from './TaskHealth'
import { InsightCard } from './InsightCard'
import { ActivityMix } from './ActivityMix'
import { CompletionGauge } from './CompletionGauge'

function rangeLabel(days: number) {
  const end = new Date()
  const start = new Date(end.getTime() - (days - 1) * 86_400_000)
  const f = (d: Date) => d.toLocaleDateString(undefined, { month: 'long', day: 'numeric' })
  return `${f(start)} – ${f(end)}`
}

export function DashboardPanel({ onNavigate }: { onNavigate?: (p: Page) => void }) {
  const { toolCallCount, sendMusicCommand } = useChatContext()
  const { data, weather, aiNews, loading, error, refresh } = useDashboard(toolCallCount)
  const a = data?.analytics
  const go = (p: Page) => (onNavigate ? () => onNavigate(p) : undefined)

  const completion = a && a.todos.total ? Math.round((a.todos.completed / a.todos.total) * 100) : 0

  return (
    <div className="flex flex-col h-full bg-crust">
      <div className="flex-1 overflow-y-auto px-4 sm:px-6 pt-5 pb-6">
        <div className="max-w-[1400px] mx-auto">
          {/* Header */}
          <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
            <h1 className="text-xl sm:text-2xl font-medium text-text tracking-tight">Mayday Overview</h1>
            <div className="flex flex-wrap items-center gap-2">
              <GmailBadge />
              <span className="hidden md:inline-flex items-center gap-2 px-3 py-1.5 text-xs text-subtext0">
                <CalendarDays className="h-3.5 w-3.5" />
                {rangeLabel(30)}
                <ChevronDown className="h-3.5 w-3.5 text-overlay1" />
              </span>
              <button
                onClick={refresh}
                disabled={loading}
                className="flex items-center gap-2 px-4 py-2 text-xs font-semibold text-black bg-green hover:bg-green/90 rounded-xl ring-1 ring-green/40 ring-offset-2 ring-offset-crust shadow-[0_0_20px_rgba(34,197,94,0.25)] transition-colors disabled:opacity-60"
              >
                Refresh
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          {error && (
            <div className="mb-4 rounded-xl bg-red/10 border border-red/30 px-4 py-2.5">
              <p className="text-xs text-red">{error}</p>
            </div>
          )}

          {loading && !data && (
            <div className="flex items-center justify-center h-48">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          )}

          {data && (
            <div className="space-y-3">
              {/* Bento grid — mirrors the reference: KPIs + tall heatmap, chart + comparison, insight/donut/gauge */}
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                <KpiCard
                  label="Open Tasks"
                  icon={ListTodo}
                  value={data.stats.open_todos}
                  badge={data.stats.overdue_todos > 0
                    ? <span className="rounded-md bg-red px-1.5 py-0.5 text-[11px] font-semibold text-white">▼ {data.stats.overdue_todos} overdue</span>
                    : <span className="rounded-md bg-green px-1.5 py-0.5 text-[11px] font-semibold text-black">▲ on track</span>}
                  onOpen={go('planner')}
                />
                <KpiCard
                  label="Upcoming Events"
                  icon={CalendarDays}
                  value={data.stats.upcoming_events_count}
                  badge={<span className="rounded-md bg-white/10 px-1.5 py-0.5 text-[11px] font-semibold text-subtext1">{data.stats.today_events} today</span>}
                  onOpen={go('planner')}
                />
                <KpiCard
                  label="Waiting on others"
                  icon={Hourglass}
                  value={data.stats.waiting_on ?? 0}
                  badge={(data.stats.follow_ups_due ?? 0) > 0
                    ? <span className="rounded-md bg-yellow px-1.5 py-0.5 text-[11px] font-semibold text-black">{data.stats.follow_ups_due} to chase</span>
                    : (data.stats.waiting_on ?? 0) > 0
                      ? <span className="rounded-md bg-white/10 px-1.5 py-0.5 text-[11px] font-semibold text-subtext1">all on track</span>
                      : undefined}
                  onOpen={go('planner')}
                />
                {a && <ActivityHeatmap analytics={a} className="xl:row-span-2" />}

                {a && <ActivityChart daily={a.daily} className="md:col-span-2" />}
                {a && <TaskHealth analytics={a} />}

                {a && <InsightCard analytics={a} />}
                {a && <ActivityMix analytics={a} className="md:col-span-1 xl:col-span-2" />}
                {a && <CompletionGauge value={completion} label="Tasks completed" onOpen={go('planner')} />}

                {/* Life row — same grid, same card language */}
                <WeatherWidget weather={weather} />
                <UpcomingEvents items={data.agenda ?? []} onOpen={go('planner')} />
                {data.music ? (
                  <MusicWidget
                    className="md:col-span-2"
                    historyStats={{
                      total_plays: data.music.total_plays,
                      language_stats: data.music.language_stats,
                      most_played_artists: [],
                      top_all: data.music.top_all,
                      top_week: data.music.top_week,
                    }}
                    onPlayTrack={(track) => sendMusicCommand({ action: 'play', ...track })}
                  />
                ) : <div className="hidden xl:block xl:col-span-2" />}

                <AINewsWidget aiNews={aiNews} className="md:col-span-2" />
                <RecentActivity
                  operations={data.recent_activity.slice(0, 6)}
                  onOpen={go('chat')}
                  className="md:col-span-2"
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
