import { X, Play, Trash2 } from 'lucide-react'
import type { MusicTrack } from '../../types/music'
import { cn } from '../../lib/utils'

interface Props {
  queue: MusicTrack[]
  currentIdx: number
  onJump: (idx: number) => void
  onClear: () => void
  onClose: () => void
}

export function PlayerQueue({ queue, currentIdx, onJump, onClear, onClose }: Props) {
  if (queue.length === 0) {
    return (
      <div className="w-full sm:w-[380px] bg-mantle border border-surface2 rounded-xl shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-surface2">
          <h3 className="text-sm font-semibold text-text">Queue</h3>
          <button onClick={onClose} className="w-7 h-7 rounded-full flex items-center justify-center text-overlay0 hover:text-text hover:bg-surface1">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-6 text-center text-sm text-overlay0">Queue is empty — ask Mayday to play something.</div>
      </div>
    )
  }

  return (
    <div className="w-full sm:w-[380px] max-h-[60vh] sm:max-h-[420px] bg-mantle border border-surface2 rounded-xl shadow-2xl flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface2 shrink-0">
        <h3 className="text-sm font-semibold text-text">Queue · {queue.length}</h3>
        <div className="flex items-center gap-1">
          <button onClick={onClear} className="flex items-center gap-1 text-xs text-overlay0 hover:text-red px-2 py-1 rounded-full hover:bg-red/10">
            <Trash2 className="h-3 w-3" /> Clear
          </button>
          <button onClick={onClose} className="w-7 h-7 rounded-full flex items-center justify-center text-overlay0 hover:text-text hover:bg-surface1">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-surface1/50">
        {queue.map((t, i) => (
          <button
            key={`${t.video_id}-${i}`}
            onClick={() => onJump(i)}
            className={cn(
              'w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-surface0/60 transition-colors',
              i === currentIdx && 'bg-green/10'
            )}
          >
            <div className="w-10 h-10 rounded-md overflow-hidden bg-surface1 shrink-0 relative">
              {t.thumb ? <img src={t.thumb} alt="" className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-[10px] text-overlay0">♪</div>}
              {i === currentIdx && (
                <div className="absolute inset-0 bg-green/30 flex items-center justify-center">
                  <Play className="h-4 w-4 text-white fill-white" />
                </div>
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p className={cn('text-xs font-medium truncate', i === currentIdx ? 'text-green' : 'text-text')}>{t.title}</p>
              <p className="text-[11px] text-overlay1 truncate">{t.artist}</p>
            </div>
            <div className="shrink-0 flex flex-col items-end gap-0.5">
              {t.language && t.language !== 'other' && (
                <span className="text-[9px] font-bold tracking-widest px-1.5 py-0.5 rounded bg-surface1 text-overlay1 border border-white/5">{t.language.toUpperCase()}</span>
              )}
              {t.duration && <span className="text-[10px] font-mono text-overlay0">{t.duration}</span>}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
