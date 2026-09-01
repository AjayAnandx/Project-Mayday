import { X, ExternalLink, PictureInPicture, Globe } from 'lucide-react'
import type { MusicTrack } from '../../types/music'

interface VideoPopupProps {
  track: MusicTrack | null
  isOpen: boolean
  onClose: () => void
  onOpenYouTube: () => void
  onPopout: () => void
}

export function VideoPopup({ track, isOpen, onClose, onOpenYouTube, onPopout }: VideoPopupProps) {
  if (!isOpen || !track) return null

  const ytUrl = `https://www.youtube.com/watch?v=${track.video_id}`
  const embedUrl = `https://www.youtube.com/embed/${track.video_id}?autoplay=0&rel=0`

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md" onClick={onClose}>
      <div
        className="relative w-full max-w-[640px] bg-black border border-green/20 rounded-2xl overflow-hidden shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-surface0/80">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-text truncate">{track.title}</p>
            <p className="text-xs text-overlay1 truncate">{track.artist} {track.language !== 'other' ? `· ${track.language.toUpperCase()}` : ''}</p>
          </div>
          <button onClick={onClose} className="ml-3 w-8 h-8 rounded-full flex items-center justify-center text-overlay0 hover:text-text hover:bg-white/10">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* youtube embed fallback — works even when our stream is audio-only or blocked */}
        <div className="aspect-video bg-black">
          <iframe
            title={track.title}
            src={embedUrl}
            className="w-full h-full"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 px-4 py-3 bg-surface0/60">
          <button
            onClick={onOpenYouTube}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-red/15 border border-red/20 text-red text-xs font-medium hover:bg-red/25"
            title="Open on YouTube in new tab"
          >
            <ExternalLink className="h-3.5 w-3.5" /> Open on YouTube
          </button>
          <button
            onClick={onPopout}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-green/15 border border-green/20 text-green text-xs font-medium hover:bg-green/25"
            title="Pop out video in separate window"
          >
            <PictureInPicture className="h-3.5 w-3.5" /> Pop out window
          </button>
          <a href={ytUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/5 border border-white/10 text-overlay1 text-xs hover:text-text">
            <Globe className="h-3.5 w-3.5" /> youtube.com
          </a>
          <span className="ml-auto text-[11px] text-overlay0 hidden sm:inline">
            {track.is_audio_only ? 'Audio-only stream' : 'Progressive video'}
          </span>
        </div>
      </div>
    </div>
  )
}
