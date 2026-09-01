import { useEffect, useState } from 'react'
import { Music2, Play, TrendingUp, Disc3 } from 'lucide-react'
import type { MusicTrack, HistoryStats, TrendingResponse } from '../../types/music'

interface Props {
  historyStats: HistoryStats | null
  onPlayTrack: (track: MusicTrack) => void
}

function pct(part: number, total: number) {
  if (total === 0) return 0
  return Math.round((part / total) * 100)
}

export function MusicWidget({ historyStats, onPlayTrack }: Props) {
  const [trending, setTrending] = useState<TrendingResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetch('/api/music/trending?count=5')
      .then(r => r.json())
      .then(data => { if (!cancelled) setTrending(data) })
      .catch(() => { if (!cancelled) setTrending({ tracks: [], country: 'IN' }) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [historyStats?.total_plays])

  const topWeek = historyStats?.top_week || []
  const topAll = historyStats?.top_all || []
  const topDisplay = topWeek.length > 0 ? topWeek : topAll
  const langStats = historyStats?.language_stats || {}
  const total = historyStats?.total_plays || 0
  const sortedLangs = Object.entries(langStats).sort((a, b) => b[1] - a[1]).slice(0, 4)

  return (
    <div className="rounded-2xl bg-surface0/60 border border-green/10 p-4 flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-xl bg-green/15 flex items-center justify-center">
          <Music2 className="h-4 w-4 text-green" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-text">Music</h3>
          <p className="text-[11px] text-overlay0">{total} plays · {sortedLangs.length ? sortedLangs.map(([k]) => k.toUpperCase()).join(' · ') : 'no history yet'}</p>
        </div>
        {trending?.biased_by && (
          <span className="text-[10px] font-medium px-2 py-1 rounded-full bg-green/10 text-green border border-green/20">
            {String(trending.biased_by).toUpperCase()} bias
          </span>
        )}
      </div>

      {/* Language mix bars */}
      {sortedLangs.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1 text-[11px] text-overlay1">
            <Disc3 className="h-3 w-3" /> Language mix
          </div>
          <div className="space-y-1">
            {sortedLangs.map(([lang, count]) => (
              <div key={lang} className="flex items-center gap-2">
                <span className="text-[11px] font-mono w-7 text-overlay1">{lang.toUpperCase()}</span>
                <div className="flex-1 h-1.5 rounded-full bg-surface1 overflow-hidden">
                  <div className="h-full bg-green rounded-full transition-all" style={{ width: `${pct(count, total)}%` }} />
                </div>
                <span className="text-[11px] font-mono text-overlay0 w-8 text-right">{pct(count, total)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top played */}
      <div className="space-y-2">
        <div className="flex items-center gap-1 text-[11px] text-overlay1">
          <Play className="h-3 w-3" /> {topWeek.length ? 'Top this week' : 'Top played'}
        </div>
        {topDisplay.length === 0 ? (
          <p className="text-xs text-overlay0 py-2">No plays yet — ask Mayday to play something.</p>
        ) : (
          <div className="space-y-1.5">
            {topDisplay.slice(0, 5).map(t => (
              <button
                key={`${t.video_id}-${t.title}`}
                onClick={() => onPlayTrack({
                  video_id: t.video_id, title: t.title, artist: t.artist, thumb: t.thumb, duration: '', language: t.language, stream_url: '',
                })}
                className="w-full flex items-center gap-2.5 p-1.5 rounded-xl hover:bg-white/5 text-left transition-colors"
              >
                <div className="w-9 h-9 rounded-lg overflow-hidden bg-surface1 shrink-0">
                  {t.thumb ? <img src={t.thumb} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-[10px] text-overlay0">♪</div>}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-text truncate">{t.title}</p>
                  <p className="text-[11px] text-overlay1 truncate">{t.artist} · ×{t.plays}</p>
                </div>
                <Play className="h-3.5 w-3.5 text-green shrink-0" />
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Trending picks */}
      <div className="space-y-2">
        <div className="flex items-center gap-1 text-[11px] text-overlay1">
          <TrendingUp className="h-3 w-3" /> Trending {trending?.country ? `· ${trending.country}` : ''}
        </div>
        {loading ? (
          <div className="flex gap-1 py-2">
            <span className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" />
            <span className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
        ) : !trending || trending.tracks.length === 0 ? (
          <p className="text-xs text-overlay0 py-1">{trending?.error || 'No trending tracks right now.'}</p>
        ) : (
          <div className="space-y-1.5">
            {trending.tracks.slice(0, 5).map(t => (
              <button
                key={t.video_id || t.title}
                onClick={() => onPlayTrack(t)}
                className="w-full flex items-center gap-2.5 p-1.5 rounded-xl hover:bg-white/5 text-left transition-colors"
              >
                <div className="w-9 h-9 rounded-lg overflow-hidden bg-surface1 shrink-0">
                  {t.thumb ? <img src={t.thumb} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-[10px] text-overlay0">♪</div>}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-text truncate">{t.title}</p>
                  <p className="text-[11px] text-overlay1 truncate">{t.artist}{t.language && t.language !== 'other' ? ` · ${t.language.toUpperCase()}` : ''}</p>
                </div>
                <Play className="h-3.5 w-3.5 text-green shrink-0" />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
