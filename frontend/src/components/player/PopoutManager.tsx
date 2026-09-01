import { X, ExternalLink, Play, Pause } from 'lucide-react'
import type { PopoutTab } from '../../hooks/useMusicPlayer'

interface PopoutManagerProps {
  tabs: PopoutTab[]
  onClose: (id: string) => void
  onFocus: (id: string) => void
  onTogglePlay: (id: string) => void
  onHide?: () => void
}

export function PopoutManager({ tabs, onClose, onFocus, onTogglePlay, onHide }: PopoutManagerProps) {
  if (tabs.length === 0) return null
  return (
    <div className="w-80 max-w-[90vw] rounded-2xl border border-green/15 bg-black/85 backdrop-blur-xl shadow-2xl overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/5 bg-surface0/60">
        <span className="text-[11px] font-bold tracking-widest text-green uppercase">Open Tabs · {tabs.length}</span>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-overlay0">{tabs.length} window{tabs.length>1?'s':''} open</span>
          {onHide && (
            <button onClick={onHide} className="w-5 h-5 rounded-full flex items-center justify-center text-overlay0 hover:text-text hover:bg-white/10">
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>
      <div className="max-h-64 overflow-y-auto divide-y divide-white/5">
        {tabs.map(t => (
          <div key={t.id} className="flex items-center gap-2 px-3 py-2.5 hover:bg-white/5 transition-colors group">
            <button
              onClick={() => onTogglePlay(t.id)}
              className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 border ${t.isPlaying ? 'bg-green text-crust border-green' : 'bg-white/10 text-text border-white/10 hover:bg-white/15'}`}
              title={t.isPlaying ? 'Pause this tab' : 'Play this tab'}
            >
              {t.isPlaying ? <Pause className="h-3.5 w-3.5 fill-crust" /> : <Play className="h-3.5 w-3.5 fill-text ml-0.5" />}
            </button>
            <div className="min-w-0 flex-1 cursor-pointer" onClick={() => onFocus(t.id)} title="Bring tab to front">
              <p className="text-xs font-medium text-text truncate">{t.title}</p>
              <p className="text-[11px] text-overlay1 truncate">{t.artist} · {t.duration || ''} · {t.startTime}s</p>
            </div>
            <button onClick={() => onFocus(t.id)} className="w-6 h-6 rounded-full flex items-center justify-center text-overlay0 hover:text-text hover:bg-white/10 shrink-0" title="Focus window">
              <ExternalLink className="h-3 w-3" />
            </button>
            <button onClick={() => onClose(t.id)} className="w-6 h-6 rounded-full flex items-center justify-center text-overlay0 hover:text-red hover:bg-red/10 shrink-0 opacity-60 group-hover:opacity-100" title="Close tab">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
      <div className="px-3 py-1.5 bg-surface0/40 border-t border-white/5 text-[10px] text-overlay0 text-center">
        Each tab is independent — pause/play per tab, focus to bring front
      </div>
    </div>
  )
}
