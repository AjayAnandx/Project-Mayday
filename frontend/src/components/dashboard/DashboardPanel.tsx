import { RefreshCw, LayoutDashboard } from 'lucide-react'
import { useChatContext } from '../../context/ChatContext'
import { useDashboard } from '../../hooks/useDashboard'
import { StatsSummary } from './StatsSummary'
import { UpcomingEvents } from './UpcomingEvents'
import { RecentActivity } from './RecentActivity'
import { WeatherWidget } from './WeatherWidget'
import { AINewsWidget } from './AINewsWidget'

export function DashboardPanel() {
  const { toolCallCount } = useChatContext()
  const { data, weather, aiNews, loading, error, refresh } = useDashboard(toolCallCount)

  return (
    <div className="flex flex-col h-full bg-crust">
      <div className="p-4 sm:p-6 pb-2 sm:pb-4">
        <div className="flex items-center justify-between mb-4 sm:mb-6">
          <div className="flex items-center gap-2 sm:gap-3">
            <div className="w-8 sm:w-10 h-8 sm:h-10 rounded-xl bg-green/15 flex items-center justify-center shrink-0">
              <LayoutDashboard className="h-4 sm:h-5 w-4 sm:w-5 text-green" />
            </div>
            <div>
              <h1 className="text-base sm:text-xl font-bold text-text">Dashboard</h1>
              <p className="text-[10px] sm:text-xs text-overlay0 hidden sm:block">Overview at a glance</p>
            </div>
          </div>
          <button
            onClick={refresh}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-overlay0 hover:text-text bg-surface0/50 hover:bg-surface1/50 rounded-full transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Refresh</span>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 sm:px-6 pb-4 sm:pb-6">
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
          <div className="space-y-4">
            <StatsSummary stats={data.stats} />

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <WeatherWidget weather={weather} />
              <UpcomingEvents events={data.upcoming_events} />
              <AINewsWidget aiNews={aiNews} />
            </div>

            <RecentActivity operations={data.recent_activity} />
          </div>
        )}
      </div>
    </div>
  )
}
