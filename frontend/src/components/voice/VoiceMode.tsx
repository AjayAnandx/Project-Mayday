import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Mic, Radio, AlertCircle } from 'lucide-react'
import { useVoiceAgent } from '../../hooks/useVoiceAgent'
import { VoiceIndicator } from './VoiceIndicator'
import { VoiceTranscript } from './VoiceTranscript'
import { MessageBubble } from '../chat/MessageBubble'

interface VoiceModeProps {
  onExit: () => void
}

const speechSupported = (): boolean => !!navigator.mediaDevices?.getUserMedia

export function VoiceMode({ onExit }: VoiceModeProps) {
  const voice = useVoiceAgent()
  const bottomRef = useRef<HTMLDivElement>(null)
  const startRef = useRef(voice.start)
  const stopRef = useRef(voice.stop)
  startRef.current = voice.start
  stopRef.current = voice.stop

  const [userInteracted, setUserInteracted] = useState(false)
  const wantListening = useRef(false)
  const beginListening = () => {
    wantListening.current = true
    startRef.current()
  }

  const recent = voice.transcript.slice(-4)

  // Browsers (Chrome esp.) block AudioContext / mic capture unless a user
  // gesture has occurred. Capture the first interaction anywhere so we can
  // start the call from within a gesture context.
  useEffect(() => {
    const onGesture = () => {
      setUserInteracted(true)
      wantListening.current = true
    }
    window.addEventListener('pointerdown', onGesture)
    window.addEventListener('keydown', onGesture)
    return () => {
      window.removeEventListener('pointerdown', onGesture)
      window.removeEventListener('keydown', onGesture)
    }
  }, [])

  // Auto-start the call once connected AND the user has interacted. Re-runs on
  // reconnect (voice.connected flips) so the call is re-established.
  useEffect(() => {
    if (speechSupported() && voice.connected && userInteracted && wantListening.current) {
      startRef.current()
    }
  }, [voice.connected, userInteracted])

  // Only stop the call on real unmount.
  useEffect(() => {
    return () => {
      stopRef.current()
      wantListening.current = false
    }
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [voice.transcript])

  if (!speechSupported()) {
    return (
      <div className="flex flex-col h-full bg-crust">
        <Header onExit={onExit} />
        <div className="flex-1 flex items-center justify-center px-6">
          <div className="flex flex-col items-center gap-3 text-center">
            <AlertCircle className="w-10 h-10 text-red" />
            <p className="text-overlay1 text-sm max-w-md">
              Voice mode requires a browser with microphone access (Chrome, Edge, or Safari).
            </p>
          </div>
        </div>
      </div>
    )
  }

  if (voice.micPermission === 'denied') {
    return (
      <div className="flex flex-col h-full bg-crust">
        <Header onExit={onExit} />
        <div className="flex-1 flex items-center justify-center px-6">
          <div className="flex flex-col items-center gap-3 text-center">
            <AlertCircle className="w-10 h-10 text-red" />
            <p className="text-overlay1 text-sm max-w-md">
              Microphone permission was denied. Allow mic access in your browser settings, then reopen Voice Mode.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-crust relative">
      <Header onExit={onExit} muted={voice.isMuted} onToggleMute={voice.toggleMute} />

      <div className="flex-1 flex flex-col items-center justify-center px-4 sm:px-6 pb-16 overflow-y-auto">
        {voice.state === 'idle' ? (
          <div className="flex flex-col items-center gap-4">
            {!voice.connected ? (
              <p className="text-overlay0 text-sm">Connecting to voice service…</p>
            ) : (
              <>
                <p className="text-overlay0 text-sm">
                  {voice.error ? voice.error : 'Microphone ready — tap to talk'}
                </p>
                <button
                  onClick={beginListening}
                  className="flex items-center gap-2 rounded-full bg-green/15 border border-green/40 px-6 py-3 text-green hover:bg-green/25 transition-all"
                >
                  <Mic className="w-5 h-5" />
                  Start Listening
                </button>
              </>
            )}
          </div>
        ) : (
          <>
            <VoiceIndicator state={voice.state} />
            <div className="mt-6 min-h-[2.5rem] flex items-center justify-center">
              <VoiceTranscript text={voice.interimText} />
              {voice.state === 'listening' && !voice.interimText && (
                <p className="text-overlay0 text-xs animate-pulse">Speak now…</p>
              )}
            </div>
          </>
        )}

        {recent.length > 0 && (
          <div className="mt-8 w-full max-w-lg mx-auto flex flex-col gap-3">
            {recent.map((m, i) => (
              <MessageBubble
                key={`${m.timestamp ?? i}-${i}`}
                message={{ id: String(i), role: m.role, content: m.text }}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        )}

        {voice.error && voice.state !== 'idle' && (
          <p className="mt-6 text-xs text-red/80 text-center max-w-md">{voice.error}</p>
        )}
      </div>
    </div>
  )
}

interface HeaderProps {
  onExit: () => void
  muted?: boolean
  onToggleMute?: () => void
}

function Header({ onExit, muted, onToggleMute }: HeaderProps) {
  return (
    <div className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-surface2">
      <div className="flex items-center gap-3">
        <button
          onClick={onExit}
          className="p-2 rounded-full bg-surface1 hover:bg-surface2 transition-colors"
        >
          <ArrowLeft className="w-5 h-5 text-subtext1" />
        </button>
        <div className="flex flex-col">
          <span className="text-sm font-semibold text-text">Voice Mode</span>
          <span className="flex items-center gap-1 text-xs text-overlay1">
            <Radio className="w-3 h-3 text-green" />
            Engine: Cloudflare
          </span>
        </div>
      </div>
      {onToggleMute && (
        <button
          onClick={onToggleMute}
          className="p-2 rounded-full bg-surface1 hover:bg-surface2 transition-colors"
          title={muted ? 'Unmute' : 'Mute'}
        >
          <Mic className={`w-5 h-5 ${muted ? 'text-overlay0' : 'text-green'}`} />
        </button>
      )}
    </div>
  )
}
