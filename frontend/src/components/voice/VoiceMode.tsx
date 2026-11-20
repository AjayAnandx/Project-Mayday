import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, MicOff, PhoneOff, Radio, AlertCircle, Zap, MessageSquare } from 'lucide-react'
import { useChatContext } from '../../context/ChatContext'
import { useBackendVoice } from '../../hooks/useBackendVoice'
import { useRealtimeVoice } from '../../hooks/useRealtimeVoice'
import { VoiceIndicator, VOICE_LABEL } from './VoiceIndicator'
import { VoiceTranscript } from './VoiceTranscript'
import { MaydayAvatar, MessageBubble } from '../chat/MessageBubble'

interface VoiceModeProps {
  onExit: () => void
}

type VoiceTab = 'realtime' | 'classic'

const speechSupported = (): boolean =>
  !!(navigator.mediaDevices?.getUserMedia)

export function VoiceMode({ onExit }: VoiceModeProps) {
  const { messages, streaming, sendMessage, connected, ingestEvent, addUserMessage } = useChatContext()
  const [mode, setMode] = useState<VoiceTab>('realtime')
  const voice = useBackendVoice({ sendMessage })
  const rt = useRealtimeVoice({ onWorkerEvent: ingestEvent, onUserTranscript: addUserMessage })
  const bottomRef = useRef<HTMLDivElement>(null)
  const prevAssistantId = useRef('')
  const prevAssistantLen = useRef(0)
  const prevStreaming = useRef(false)
  const feedTokensRef = useRef(voice.feedTokens)
  const flushTtsRef = useRef(voice.flushTts)
  feedTokensRef.current = voice.feedTokens
  flushTtsRef.current = voice.flushTts
  const startVoiceRef = useRef(voice.start)
  const stopVoiceRef = useRef(voice.stop)
  startVoiceRef.current = voice.start
  stopVoiceRef.current = voice.stop

  // Pipe streaming assistant tokens to classic TTS progressively (classic only)
  useEffect(() => {
    if (mode !== 'classic') return
    const last = messages[messages.length - 1]

    if (last?.role === 'user') {
      prevAssistantId.current = ''
      prevAssistantLen.current = 0
    } else if (last?.role === 'assistant') {
      if (last.id !== prevAssistantId.current) {
        prevAssistantId.current = last.id
        prevAssistantLen.current = 0
        // If the message has a dedicated voice summary, use it directly
        if (last.voice_content) {
          feedTokensRef.current(last.voice_content)
          prevAssistantLen.current = -1
        }
      }
      // Fall back to content-diff if no voice_content
      if (!last.voice_content && prevAssistantLen.current >= 0) {
        const prevLen = prevAssistantLen.current
        const currLen = last.content.length
        if (currLen > prevLen) {
          feedTokensRef.current(last.content.slice(prevLen))
          prevAssistantLen.current = currLen
        }
      }
    }

    if (prevStreaming.current && !streaming) {
      flushTtsRef.current()
    }
    prevStreaming.current = streaming
  }, [messages, streaming, mode])

  // Speak finished-research announcements while classic voice is open
  useEffect(() => {
    if (mode !== 'classic') return
    const onSpeak = (e: Event) => {
      const text = (e as CustomEvent<{ text?: string }>).detail?.text
      if (!text) return
      feedTokensRef.current(text)
      flushTtsRef.current()
    }
    window.addEventListener('mayday-speak', onSpeak)
    return () => window.removeEventListener('mayday-speak', onSpeak)
  }, [mode])

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Start classic voice on mount — hook handles mic access internally
  useEffect(() => {
    if (mode !== 'classic') return
    if (connected && voice.state === 'idle') {
      startVoiceRef.current()
    }
    return () => stopVoiceRef.current()
  }, [connected, mode])

  // Stop whichever engine is running when switching tabs / unmounting
  useEffect(() => {
    return () => {
      stopVoiceRef.current()
      rt.stop()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const switchMode = (next: VoiceTab) => {
    if (next === mode) return
    voice.stop()
    rt.stop()
    setMode(next)
  }

  const engine = mode === 'realtime'
    ? (rt.status?.ready ? `Realtime · ${rt.status.model}` : 'Realtime offline')
    : 'Deepgram'
  const activeVoice = mode === 'realtime' ? rt : voice
  const transcript = messages.slice(-12)

  if (!speechSupported() || !activeVoice.isSupported) {
    return (
      <StateCard onExit={onExit} icon={<AlertCircle className="h-6 w-6 text-yellow" />}
                 title="Voice isn't available in this browser"
                 body="Voice needs microphone and audio support — use a recent Chrome or Edge." />
    )
  }
  if (!connected) {
    return (
      <StateCard onExit={onExit} icon={<span className="w-3 h-3 rounded-full bg-yellow animate-pulse" />}
                 title="Connecting to Mayday…" body="Voice starts as soon as the assistant is reachable." />
    )
  }
  if (activeVoice.micPermission === 'denied') {
    return (
      <StateCard onExit={onExit} icon={<MicOff className="h-6 w-6 text-red" />}
                 title="Microphone is blocked"
                 body="Allow microphone access for this site in your browser settings, then come back." />
    )
  }

  const rtUnavailable = mode === 'realtime' && !!rt.status && !rt.status.ready
  const requesting = mode === 'classic' && voice.micPermission === 'unknown' && voice.state === 'idle'
  const state = mode === 'realtime' ? rt.state : voice.state
  const interim = mode === 'realtime' ? rt.interimText : voice.interimText
  const toggle = () => {
    if (mode === 'realtime') {
      if (rt.state === 'idle') rt.start()
      else rt.stop()
    } else if (voice.state === 'idle') {
      voice.start()
    } else {
      voice.stop()
    }
  }

  const hint = state === 'listening' ? "Go ahead — I'm listening."
    : state === 'speaking' ? 'Speak any time to interrupt.'
    : state === 'processing' ? 'Working on it…'
    : mode === 'realtime' ? 'Low-latency conversation. Heavier jobs go to the background worker.'
    : 'Speech-to-text in your browser, replies read aloud.'

  return (
    <div className="h-full bg-crust overflow-hidden">
      <div className="h-full max-w-[1400px] mx-auto px-3 sm:px-6 pt-4 pb-4 flex flex-col gap-4">
        {/* top bar */}
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={onExit} aria-label="Exit voice"
                  className="w-9 h-9 rounded-full border border-white/10 flex items-center justify-center text-subtext0 hover:text-text hover:bg-white/5">
            <ArrowLeft className="h-4 w-4" />
          </button>
          <h1 className="text-xl font-medium tracking-tight text-text mr-auto">Voice</h1>
          <div className="flex rounded-[12px] bg-white/[0.04] border border-white/[0.06] p-0.5" role="tablist" aria-label="Voice engine">
            {([['realtime', 'Realtime', Zap], ['classic', 'Classic', MessageSquare]] as const).map(([id, label, Icon]) => (
              <button key={id} role="tab" aria-selected={mode === id} onClick={() => switchMode(id)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-[10px] text-xs font-medium transition-colors ${mode === id ? 'bg-text text-black' : 'text-subtext0 hover:text-text'}`}>
                <Icon className="h-3.5 w-3.5" /> {label}
              </button>
            ))}
          </div>
          <span className="hidden sm:flex items-center gap-1.5 rounded-full border border-white/10 px-3 py-1.5 text-[11px] text-overlay2">
            <Radio className="h-3 w-3" /> {engine}
          </span>
        </div>

        <div className="flex-1 min-h-0 grid gap-4 lg:grid-cols-[1fr_380px] overflow-y-auto lg:overflow-visible">
          {/* stage */}
          <section className="relative min-h-[460px] rounded-[24px] border border-white/[0.06] bg-[#080808] bg-[radial-gradient(ellipse_at_center,rgba(34,197,94,0.08),transparent_65%)] flex flex-col items-center justify-center px-6 py-12 overflow-hidden">
            {(rtUnavailable || (mode === 'realtime' && rt.statusError)) && (
              <div className="absolute top-4 inset-x-4 mx-auto max-w-md flex items-start gap-2 rounded-2xl border border-yellow/25 bg-yellow/[0.08] px-4 py-2.5 text-xs text-yellow">
                <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>
                  {rt.statusError || <>Realtime voice is unavailable{rt.status?.reason ? ` (${rt.status.reason})` : ''}.</>}{' '}
                  <button onClick={() => switchMode('classic')} className="underline hover:text-text">Use Classic voice</button>
                </span>
              </div>
            )}

            <VoiceIndicator state={state} onToggle={requesting ? undefined : toggle}
                            disabled={rtUnavailable && state === 'idle'} />

            <p role="status" className={`mt-6 text-xs font-semibold uppercase tracking-[0.2em] ${state === 'idle' ? 'text-overlay1' : 'text-green'}`}>
              {requesting ? 'Requesting microphone…' : rtUnavailable && state === 'idle' ? 'Realtime offline' : VOICE_LABEL[state]}
            </p>

            <div className="mt-4 min-h-[3.5rem] flex items-center justify-center">
              {interim
                ? <VoiceTranscript text={interim} />
                : <p className="text-sm text-overlay1 text-center max-w-sm">{hint}</p>}
            </div>

            {state !== 'idle' && (
              <button onClick={toggle}
                      className="mt-6 flex items-center gap-2 rounded-full bg-red/10 border border-red/25 px-4 py-2 text-xs font-medium text-red hover:bg-red/15">
                <PhoneOff className="h-3.5 w-3.5" /> End session
              </button>
            )}
          </section>

          {/* transcript */}
          <aside className="min-h-[260px] lg:min-h-0 flex flex-col rounded-[20px] border border-white/[0.06] bg-[#0b0b0b]" aria-label="Conversation">
            <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-white/[0.05]">
              <h2 className="text-sm text-subtext1">Conversation</h2>
              <button onClick={() => window.dispatchEvent(new CustomEvent('navigate', { detail: 'chat' }))}
                      className="text-[11px] text-overlay1 hover:text-text">Open in chat</button>
            </div>
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
              {transcript.length === 0 ? (
                <div className="h-full min-h-[140px] rounded-2xl bg-hatch border border-white/[0.04] flex items-center justify-center text-center px-6">
                  <p className="text-xs text-overlay1">What you say and what Mayday replies will appear here.</p>
                </div>
              ) : transcript.map(msg => <MessageBubble key={msg.id} message={msg} compact />)}
              {streaming && (
                <div className="flex items-center gap-2" role="status" aria-label="Mayday is thinking">
                  <MaydayAvatar size="sm" pulse />
                  <div className="flex gap-1">
                    {[0, 150, 300].map(d => (
                      <span key={d} className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" style={{ animationDelay: `${d}ms` }} />
                    ))}
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </aside>
        </div>
      </div>
    </div>
  )
}

function StateCard({ onExit, icon, title, body }: {
  onExit: () => void
  icon: React.ReactNode
  title: string
  body: string
}) {
  return (
    <div className="h-full bg-crust flex items-center justify-center px-6">
      <div className="max-w-sm w-full rounded-[24px] border border-white/[0.06] bg-[#0b0b0b] p-8 flex flex-col items-center text-center gap-3">
        <span className="w-12 h-12 rounded-2xl bg-white/[0.05] flex items-center justify-center">{icon}</span>
        <p className="text-base text-text">{title}</p>
        <p className="text-xs text-subtext0 leading-relaxed">{body}</p>
        <button onClick={onExit} className="mt-2 rounded-xl border border-white/10 px-4 py-2 text-xs text-subtext1 hover:bg-white/5">
          Go back
        </button>
      </div>
    </div>
  )
}
