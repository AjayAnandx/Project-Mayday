import { useEffect } from 'react'
import { Play, Pause, SkipBack, SkipForward, Volume2, VolumeX, X, ListMusic, Repeat, Maximize2, Minimize2, Loader2, ExternalLink, PictureInPicture, Heart, Infinity } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { MusicTrack } from '../../types/music'

interface PlayerBarProps {
  current: MusicTrack | null
  queue: MusicTrack[]
  isPlaying: boolean
  currentTime: number
  duration: number
  volume: number
  repeat: boolean
  autoPlay?: boolean
  expanded: boolean
  needsGesture: boolean
  playError: string | null
  resolving: boolean
  setExpanded: (v: boolean) => void
  onPlay: () => void
  onPause: () => void
  onNext: () => void
  onPrev: () => void
  onSeek: (t: number) => void
  onVolume: (v: number) => void
  onToggleRepeat: () => void
  onToggleAutoPlay?: () => void
  onClear: () => void
  onToggleQueue: () => void
  showQueue: boolean
  videoRef: React.RefObject<HTMLVideoElement>
  audioRef: React.RefObject<HTMLAudioElement>
  onOpenYouTube?: () => void
  onPopout?: () => void
  onToggleFavorite?: () => void
  isFavorite?: boolean
}

function fmt(t: number) {
  if (!isFinite(t) || t < 0) return '0:00'
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

export function PlayerBar({
  current, queue, isPlaying, currentTime, duration, volume, repeat, autoPlay = true, expanded, needsGesture, playError, resolving, setExpanded,
  onPlay, onPause, onNext, onPrev, onSeek, onVolume, onToggleRepeat, onToggleAutoPlay, onClear, onToggleQueue, showQueue, videoRef, audioRef,
  onOpenYouTube, onPopout, onToggleFavorite, isFavorite,
}: PlayerBarProps) {
  const hasTrack = !!current
  const hasQueue = queue.length > 0
  const progressPct = duration > 0 ? (currentTime / duration) * 100 : 0

  // keyboard space to toggle
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.code === 'Space' && hasTrack && (e.target as HTMLElement)?.tagName !== 'INPUT' && (e.target as HTMLElement)?.tagName !== 'TEXTAREA') {
        e.preventDefault()
        if (isPlaying) onPause(); else onPlay()
      }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [hasTrack, isPlaying, onPause, onPlay])

  const isAudioOnly = !!current?.is_audio_only
  // Keep shell mounted even when empty so refs stay alive for first track race.
  const isEmpty = !hasTrack && !hasQueue

  return (
    <div className={cn('shrink-0 border-t bg-black/80 backdrop-blur-xl', isEmpty ? 'hidden' : 'border-green/15')}>
      {needsGesture && hasTrack && !isPlaying && (
        <button onClick={onPlay} className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-amber-500/15 border-b border-amber-500/20 text-amber-300 text-xs font-medium hover:bg-amber-500/20 transition-colors">
          <Play className="h-3.5 w-3.5 fill-amber-300" /> Tap to play — browser blocked autoplay
        </button>
      )}
      {playError && hasTrack && (
        <div className="w-full px-3 py-1.5 bg-red/10 border-b border-red/20 text-red text-[11px] text-center truncate" title={playError}>{playError}</div>
      )}
      {resolving && hasTrack && (
        <div className="w-full flex items-center justify-center gap-2 px-3 py-1.5 bg-green/10 border-b border-green/20 text-green text-[11px] font-medium">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Resolving stream…
        </div>
      )}
      {isAudioOnly && hasTrack && !resolving && (
        <div className="w-full px-3 py-1 flex items-center justify-center gap-1.5 bg-surface1/60 border-b border-white/5 text-[11px] text-overlay1">
          <span className="w-1.5 h-1.5 rounded-full bg-green animate-pulse" /> Audio-only stream
        </div>
      )}
      {/* both media elements always mounted — only one is active; no crossOrigin (googlevideo CORS fails with it) */}
      <video
        ref={videoRef}
        className={cn('bg-black', expanded && !isAudioOnly ? 'w-full h-[180px] sm:h-[220px] max-w-[400px] mx-auto block' : 'hidden')}
        playsInline
        autoPlay
        preload="auto"
        controls={false}
      />
      <audio
        ref={audioRef}
        className="hidden"
        preload="auto"
        autoPlay
      />
      {isEmpty ? null : (
        <>

      <div className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2 sm:py-2.5">
        {/* thumb + meta */}
        <div className="flex items-center gap-2 sm:gap-3 min-w-0 flex-1">
          <div className="w-10 h-10 sm:w-11 sm:h-11 rounded-lg overflow-hidden bg-surface1 shrink-0 border border-white/5">
            {current?.thumb ? (
              <img src={current.thumb} alt="" className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-overlay0 text-[10px]">♪</div>
            )}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 min-w-0">
              <p className="text-xs sm:text-sm font-medium text-text truncate">{current?.title || 'No track'}</p>
              {current?.language && current.language !== 'other' && (
                <span className="shrink-0 text-[9px] font-bold tracking-widest px-1.5 py-0.5 rounded bg-green/15 text-green border border-green/20">
                  {current.language.toUpperCase()}
                </span>
              )}
              {((current as any)?.genre || (current as any)?.mood) && (current as any)?.genre !== current?.language && (
                <span className="shrink-0 text-[9px] font-medium px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-500/20 max-w-[80px] truncate">
                  {((current as any).genre || (current as any).mood).toString().slice(0,12)}
                </span>
              )}
            </div>
            <p className="text-[11px] text-overlay1 truncate">{current?.artist || (queue.length ? `${queue.length} in queue` : '')}</p>
          </div>
          {!hasTrack && queue.length > 0 && (
            <span className="text-[10px] text-overlay0 hidden sm:inline">{queue.length} queued</span>
          )}
        </div>

        {/* center controls */}
        <div className="flex items-center gap-1 shrink-0">
          <button onClick={onPrev} disabled={!hasTrack || resolving} className="w-7 h-7 sm:w-8 sm:h-8 rounded-full flex items-center justify-center text-overlay1 hover:text-text hover:bg-white/10 disabled:opacity-30 transition-colors">
            <SkipBack className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
          </button>
          <button
            onClick={isPlaying ? onPause : onPlay}
            disabled={!hasTrack || resolving}
            className={cn('w-8 h-8 sm:w-9 sm:h-9 rounded-full bg-green text-crust flex items-center justify-center hover:bg-green/90 disabled:opacity-30 shadow shadow-green/20 transition-colors', resolving && 'opacity-60')}
          >
            {resolving ? <Loader2 className="h-3.5 w-3.5 sm:h-4 sm:w-4 animate-spin text-crust" /> : isPlaying ? <Pause className="h-3.5 w-3.5 sm:h-4 sm:w-4 fill-crust" /> : <Play className="h-3.5 w-3.5 sm:h-4 sm:w-4 fill-crust ml-0.5" />}
          </button>
          <button onClick={onNext} disabled={(queue.length <= 1 && !repeat) || resolving} className="w-7 h-7 sm:w-8 sm:h-8 rounded-full flex items-center justify-center text-overlay1 hover:text-text hover:bg-white/10 disabled:opacity-30 transition-colors">
            <SkipForward className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
          </button>
          <button onClick={onToggleRepeat} className={cn('w-7 h-7 rounded-full flex items-center justify-center transition-colors hidden sm:flex', repeat ? 'text-green bg-green/15' : 'text-overlay0 hover:text-text hover:bg-white/10')} title={repeat ? 'Repeat on' : 'Repeat off'}>
            <Repeat className="h-3.5 w-3.5" />
          </button>
          {onToggleAutoPlay && (
            <button onClick={onToggleAutoPlay} className={cn('w-7 h-7 rounded-full flex items-center justify-center transition-colors hidden sm:flex', autoPlay ? 'text-green bg-green/15' : 'text-overlay0 hover:text-text hover:bg-white/10')} title={autoPlay ? 'Auto-play next in genre: ON' : 'Auto-play next in genre: OFF'}>
              <Infinity className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* volume + queue + expand + video actions */}
        <div className="hidden sm:flex items-center gap-1 shrink-0">
          {onToggleFavorite && (
            <button onClick={onToggleFavorite} disabled={!current} className={cn('w-7 h-7 rounded-full flex items-center justify-center transition-colors', isFavorite ? 'text-red bg-red/15 border border-red/20' : 'text-overlay0 hover:text-red hover:bg-red/10')} title={isFavorite ? 'Remove from favorites' : 'Add to favorites'}>
              <Heart className={cn('h-4 w-4', isFavorite && 'fill-red')} />
            </button>
          )}
          {onOpenYouTube && (
            <button onClick={onOpenYouTube} disabled={!current} className="w-7 h-7 rounded-full flex items-center justify-center text-overlay0 hover:text-text hover:bg-white/10 disabled:opacity-30" title="Open on YouTube">
              <ExternalLink className="h-3.5 w-3.5" />
            </button>
          )}
          {onPopout && (
            <button onClick={onPopout} disabled={!current} className="w-7 h-7 rounded-full flex items-center justify-center text-overlay0 hover:text-text hover:bg-white/10 disabled:opacity-30" title="Pop out video in new window">
              <PictureInPicture className="h-3.5 w-3.5" />
            </button>
          )}
          <button onClick={() => onVolume(volume > 0 ? 0 : 0.85)} className="w-7 h-7 rounded-full flex items-center justify-center text-overlay0 hover:text-text hover:bg-white/10">
            {volume === 0 ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
          </button>
          <input
            type="range" min={0} max={1} step={0.05} value={volume}
            onChange={e => onVolume(parseFloat(e.target.value))}
            className="w-20 accent-green h-1"
            title="Volume"
          />
          <button onClick={() => setExpanded(!expanded)} className="w-7 h-7 rounded-full flex items-center justify-center text-overlay0 hover:text-text hover:bg-white/10" title={expanded ? 'Collapse video' : 'Expand video'}>
            {expanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
          <button onClick={onToggleQueue} className={cn('w-7 h-7 rounded-full flex items-center justify-center', showQueue ? 'text-green bg-green/15' : 'text-overlay0 hover:text-text hover:bg-white/10')}>
            <ListMusic className="h-4 w-4" />
          </button>
          <button onClick={onClear} className="w-7 h-7 rounded-full flex items-center justify-center text-overlay0 hover:text-red hover:bg-red/10" title="Clear queue">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* mobile actions */}
        <div className="sm:hidden flex items-center gap-1 shrink-0">
          {onToggleFavorite && (
            <button onClick={onToggleFavorite} disabled={!current} className={cn('w-7 h-7 rounded-full flex items-center justify-center', isFavorite ? 'text-red bg-red/15' : 'text-overlay0')}>
              <Heart className={cn('h-3.5 w-3.5', isFavorite && 'fill-red')} />
            </button>
          )}
          {onPopout && (
            <button onClick={onPopout} disabled={!current} className="w-7 h-7 rounded-full flex items-center justify-center text-overlay0 disabled:opacity-30">
              <PictureInPicture className="h-3.5 w-3.5" />
            </button>
          )}
          {onOpenYouTube && (
            <button onClick={onOpenYouTube} disabled={!current} className="w-7 h-7 rounded-full flex items-center justify-center text-overlay0 disabled:opacity-30">
              <ExternalLink className="h-3.5 w-3.5" />
            </button>
          )}
          <button onClick={onToggleQueue} className={cn('w-7 h-7 rounded-full flex items-center justify-center shrink-0', showQueue ? 'text-green bg-green/15' : 'text-overlay0')}>
            <ListMusic className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* seek bar */}
      <div className="px-3 sm:px-4 pb-2 flex items-center gap-2">
        <span className="text-[10px] font-mono text-overlay0 w-8 text-right">{fmt(currentTime)}</span>
        <div className="flex-1 relative h-1.5 rounded-full bg-surface1 overflow-hidden group cursor-pointer" onClick={e => {
          const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
          const pct = (e.clientX - rect.left) / rect.width
          onSeek(pct * duration)
        }}>
          <div className="absolute inset-y-0 left-0 bg-green transition-all" style={{ width: `${progressPct}%` }} />
          <input
            type="range" min={0} max={duration || 100} step={0.1} value={currentTime}
            onChange={e => onSeek(parseFloat(e.target.value))}
            className="absolute inset-0 w-full opacity-0 cursor-pointer"
          />
        </div>
        <span className="text-[10px] font-mono text-overlay0 w-8">{fmt(duration)}</span>
        <button onClick={() => setExpanded(!expanded)} className="sm:hidden w-6 h-6 rounded flex items-center justify-center text-overlay0">
          {expanded ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}
        </button>
      </div>
        </>
      )}
    </div>
  )
}
