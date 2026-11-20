import { Loader2, Mic, MicOff } from 'lucide-react'
import type { VoiceState } from '../../hooks/useVoice'
import { cn } from '../../lib/utils'

export const VOICE_LABEL: Record<VoiceState, string> = {
  idle: 'Tap to talk',
  listening: 'Listening',
  processing: 'Thinking',
  speaking: 'Speaking',
  proactive: 'Mayday has something',
}

interface VoiceOrbProps {
  state: VoiceState
  /** idle → start, active → stop */
  onToggle?: () => void
  disabled?: boolean
}

/**
 * Animated orb that doubles as the session button.
 * listening = ripples · thinking = spinning ring · speaking = live bars · idle = calm.
 */
export function VoiceIndicator({ state, onToggle, disabled }: VoiceOrbProps) {
  const active = state !== 'idle'
  return (
    <div className="relative w-56 h-56 sm:w-64 sm:h-64 flex items-center justify-center">
      {/* ambient glow */}
      <span aria-hidden className={cn('absolute inset-6 rounded-full blur-3xl transition-opacity duration-700',
        state === 'processing' ? 'bg-white/10' : 'bg-green/25', active ? 'opacity-100' : 'opacity-40')} />

      {(state === 'listening' || state === 'proactive') && [0, 0.8, 1.6].map(d => (
        <span key={d} aria-hidden className="orb-ripple absolute inset-10 rounded-full border border-green/50"
              style={{ animationDelay: `${d}s` }} />
      ))}

      {state === 'processing' && (
        <span aria-hidden className="absolute inset-7 rounded-full animate-spin [animation-duration:1.6s]"
              style={{ background: 'conic-gradient(from 0deg, transparent 0deg, rgba(74,222,128,0.9) 80deg, transparent 160deg)', mask: 'radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 2px))', WebkitMask: 'radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 2px))' }} />
      )}

      <button
        type="button"
        onClick={onToggle}
        disabled={disabled || !onToggle}
        aria-label={active ? 'End voice session' : 'Start voice session'}
        aria-pressed={active}
        className={cn(
          'relative w-36 h-36 sm:w-40 sm:h-40 rounded-full flex items-center justify-center transition-all duration-500',
          'bg-[radial-gradient(circle_at_35%_30%,#4ade80_0%,#16a34a_45%,#052e16_100%)]',
          'shadow-[inset_0_-12px_30px_rgba(0,0,0,0.45),0_0_60px_rgba(34,197,94,0.25)]',
          !active && 'orb-breathe saturate-[0.55] brightness-75 hover:saturate-100 hover:brightness-100',
          state === 'processing' && 'saturate-[0.4] brightness-90',
          'disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-green focus-visible:ring-offset-4 focus-visible:ring-offset-crust',
        )}
      >
        <span aria-hidden className="absolute inset-0 rounded-full bg-[radial-gradient(circle_at_30%_22%,rgba(255,255,255,0.35),transparent_40%)]" />
        {state === 'speaking' ? (
          <span className="relative flex items-center gap-1.5 h-12" aria-hidden>
            {[0.1, 0.35, 0, 0.5, 0.2, 0.4, 0.05].map((d, i) => (
              <span key={i} className="orb-bar w-1.5 h-full rounded-full bg-black/70" style={{ animationDelay: `${d}s` }} />
            ))}
          </span>
        ) : state === 'processing' ? (
          <Loader2 className="relative h-10 w-10 text-black/70 animate-spin" aria-hidden />
        ) : active ? (
          <Mic className="relative h-11 w-11 text-black/75" aria-hidden />
        ) : disabled ? (
          <MicOff className="relative h-10 w-10 text-black/60" aria-hidden />
        ) : (
          <Mic className="relative h-10 w-10 text-black/70" aria-hidden />
        )}
      </button>
    </div>
  )
}
