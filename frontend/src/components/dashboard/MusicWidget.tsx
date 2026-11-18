import { useEffect, useState } from 'react'
import { Music2, Play, TrendingUp } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { MusicTrack, HistoryStats, TrendingResponse } from '../../types/music'
import { DashCard, CardHeader, compact } from './DashCard'

interface Props {
  historyStats: HistoryStats | null
  onPlayTrack: (track: MusicTrack) => void
  className?: string
}

const LANG_SHADES = ['bg-green', 'bg-green/55', 'bg-green/25', 'bg-surface2']

function pct(part: number, total: number) {
  return total ? Math.round((part / total) * 100) : 0
}

function Thumb({ src, className }: { src?: string; className?: string }) {
  return (
    <div className={cn('overflow-hidden bg-surface1 shrink-0', className)}>
      {src
        ? <img src={src} alt="" className="w-full h-full object-cover" loading="lazy" />
        : <div className="w-full h-full flex items-center justify-center text-overlay0">♪</div>}
    </div>
  )
}

export function MusicWidget({ historyStats, onPlayTrack, className }: Props) {
  const [trending, setTrending] = useState<TrendingResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch('/api/music/trending?count=4')
      .then(r => r.json())
      .then(d => { if (!cancelled) setTrending(d) })
      .catch(() => { if (!cancelled) setTrending({ tracks: [], country: 'IN' }) })
    return () => { cancelled = true }
  }, [historyStats?.total_plays])

  const topWeek = historyStats?.top_week ?? []
  const top = (topWeek.length ? topWeek : historyStats?.top_all ?? []).slice(0, 4)
  const total = historyStats?.total_plays ?? 0
  const langs = Object.entries(historyStats?.language_stats ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 4)

  const toTrack = (t: typeof top[number]): MusicTrack => ({
    video_id: t.video_id, title: t.title, artist: t.artist, thumb: t.thumb, duration: '', language: t.language, stream_url: '',
  })

  return (
    <DashCard className={className}>
      <CardHeader
        title="Music"
        icon={Music2}
        right={trending?.biased_by && (
          <span className="rounded-full border border-white/10 px-3 py-1 text-[11px] text-subtext0">
            {String(trending.biased_by).toUpperCase()} picks
          </span>
        )}
      />

      <div className="grid sm:grid-cols-[180px_1fr] gap-5">
        {/* Plays + language split */}
        <div>
          <p className="text-[44px] leading-none font-medium tracking-tight text-text tabular-nums">{compact(total)}</p>
          <p className="text-[11px] text-overlay1 mt-1.5">Total plays</p>
          {langs.length > 0 && (
            <>
              <div className="flex h-1.5 rounded-full overflow-hidden gap-0.5 mt-5 bg-surface1">
                {langs.map(([l, c], i) => (
                  <div key={l} className={LANG_SHADES[i]} style={{ width: `${pct(c, total)}%` }} />
                ))}
              </div>
              <ul className="mt-3 space-y-1.5">
                {langs.map(([l, c], i) => (
                  <li key={l} className="flex items-center gap-2 text-xs">
                    <span className={cn('w-2 h-2 rounded-full', LANG_SHADES[i])} />
                    <span className="flex-1 uppercase text-subtext0">{l}</span>
                    <span className="text-text tabular-nums">{pct(c, total)}%</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        {/* Top played tiles */}
        <div className="min-w-0">
          <p className="text-[11px] text-overlay1 mb-2">{topWeek.length ? 'Top this week' : 'Most played'}</p>
          {top.length === 0 ? (
            <div className="rounded-2xl bg-hatch border border-white/[0.04] py-8 text-center text-xs text-overlay1">
              No plays yet — ask Mayday to play something.
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              {top.map(t => (
                <button
                  key={`${t.video_id}-${t.title}`}
                  onClick={() => onPlayTrack(toTrack(t))}
                  className="group flex items-center gap-2.5 rounded-2xl bg-white/[0.03] border border-white/[0.05] p-2 text-left hover:bg-white/[0.06] transition-colors min-w-0"
                >
                  <div className="relative">
                    <Thumb src={t.thumb} className="w-11 h-11 rounded-xl" />
                    <span className="absolute inset-0 rounded-xl bg-black/50 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity">
                      <Play className="h-4 w-4 text-green fill-green" />
                    </span>
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs text-text truncate">{t.title}</p>
                    <p className="text-[10px] text-overlay1 truncate">{t.artist}</p>
                    <p className="text-[10px] text-green tabular-nums mt-0.5">×{t.plays}</p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Trending strip */}
      {trending && trending.tracks.length > 0 && (
        <div className="mt-5 pt-4 border-t border-white/[0.05]">
          <p className="flex items-center gap-1.5 text-[11px] text-overlay1 mb-2">
            <TrendingUp className="h-3 w-3" /> Trending{trending.country ? ` · ${trending.country}` : ''}
          </p>
          <div className="flex gap-2 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {trending.tracks.slice(0, 4).map(t => (
              <button
                key={t.video_id || t.title}
                onClick={() => onPlayTrack(t)}
                className="flex items-center gap-2 rounded-full bg-white/[0.03] border border-white/[0.05] pl-1 pr-3 py-1 shrink-0 max-w-[220px] hover:bg-white/[0.06] transition-colors"
              >
                <Thumb src={t.thumb} className="w-7 h-7 rounded-full" />
                <span className="text-[11px] text-subtext1 truncate">{t.title}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </DashCard>
  )
}
