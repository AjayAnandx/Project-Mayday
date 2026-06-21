import type { VoiceState } from '../../hooks/useVoice'
import { cn } from '../../lib/utils'

interface VoiceIndicatorProps {
  state: VoiceState
}

const stateConfig: Record<VoiceState, { label: string; color: string; glow: string }> = {
  idle: { label: '', color: 'border-overlay0', glow: '' },
  listening: { label: 'Listening', color: 'border-green', glow: 'shadow-green/40' },
  processing: { label: 'Processing', color: 'border-yellow', glow: 'shadow-yellow/40' },
  speaking: { label: 'Speaking', color: 'border-blue', glow: 'shadow-blue/40' },
  proactive: { label: 'Mayday', color: 'border-amber', glow: 'shadow-amber/40' },
}

export function VoiceIndicator({ state }: VoiceIndicatorProps) {
  if (state === 'idle') return null
  const cfg = stateConfig[state]

  return (
    <div className="flex flex-col items-center gap-6">
      <div className="relative">
        <div
          className={cn(
            'w-28 h-28 rounded-full border-2 transition-all duration-500',
            cfg.color,
            'shadow-2xl',
            cfg.glow,
          )}
        >
          <div
            className={cn(
              'w-full h-full rounded-full flex items-center justify-center',
              'bg-gradient-to-br from-transparent via-white/[0.03] to-transparent',
              state === 'listening' && 'animate-pulse shadow-inner',
              state === 'speaking' && 'animate-pulse shadow-inner',
              state === 'processing' && 'animate-pulse shadow-inner',
              state === 'proactive' && 'animate-pulse shadow-inner',
            )}
          >
            <div
              className={cn(
                'w-20 h-20 rounded-full transition-all duration-500',
                'flex items-center justify-center',
                state === 'listening' && 'bg-green/10',
                state === 'speaking' && 'bg-blue/10',
                state === 'processing' && 'bg-yellow/10',
                state === 'proactive' && 'bg-amber/10',
              )}
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                className={cn(
                  'w-10 h-10 transition-colors duration-500',
                  state === 'listening' && 'text-green',
                  state === 'speaking' && 'text-blue',
                  state === 'processing' && 'text-yellow',
                  state === 'proactive' && 'text-amber',
                )}
              >
                <path
                  d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"
                  fill="currentColor"
                />
                <path
                  d="M19 10v2a7 7 0 0 1-14 0v-2"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
                <line x1="12" y1="19" x2="12" y2="23" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </div>
          </div>
        </div>

        {state === 'listening' && (
          <>
            <span className="absolute -top-1 -right-1 w-4 h-4 bg-green rounded-full animate-ping opacity-75" />
            <span className="absolute -top-1 -right-1 w-4 h-4 bg-green rounded-full" />
          </>
        )}
      </div>

      <span
        className={cn(
          'text-lg font-semibold tracking-wide',
          state === 'listening' && 'text-green',
          state === 'speaking' && 'text-blue',
          state === 'processing' && 'text-yellow',
          state === 'proactive' && 'text-amber',
        )}
      >
        {cfg.label}
      </span>
    </div>
  )
}
