import { useEffect, useRef } from 'react'
import { ArrowLeft, Mic, Radio, AlertCircle } from 'lucide-react'
import { useChatContext } from '../../context/ChatContext'
import { useBackendVoice } from '../../hooks/useBackendVoice'
import { VoiceIndicator } from './VoiceIndicator'
import { VoiceTranscript } from './VoiceTranscript'
import { MessageBubble } from '../chat/MessageBubble'

interface VoiceModeProps {
  onExit: () => void
}

const speechSupported = (): boolean =>
  !!(navigator.mediaDevices?.getUserMedia)

function getEngineLabel(): string {
  return 'Deepgram'
}

export function VoiceMode({ onExit }: VoiceModeProps) {
  const { messages, streaming, sendMessage, connected } = useChatContext()
  const voice = useBackendVoice({ sendMessage })
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

  // Pipe streaming assistant tokens to TTS progressively
  useEffect(() => {
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
  }, [messages, streaming])

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Start voice on mount — hook handles mic access internally
  useEffect(() => {
    if (connected && voice.state === 'idle') {
      startVoiceRef.current()
    }
    return () => stopVoiceRef.current()
  }, [connected])

  const recentMessages = messages.slice(-4)
  const engine = getEngineLabel()

  if (!speechSupported()) {
    return (
      <div className="flex flex-col h-full bg-crust items-center justify-center gap-4 px-6">
        <p className="text-overlay0 text-sm text-center">
          Voice mode requires Chrome, Edge, or Firefox.<br />
          Your browser doesn't support microphone access.
        </p>
        <button onClick={onExit} className="text-green text-sm underline">Go back</button>
      </div>
    )
  }

  if (!voice.isSupported) {
    return (
      <div className="flex flex-col h-full bg-crust items-center justify-center gap-4 px-6">
        <AlertCircle className="w-8 h-8 text-overlay0" />
        <p className="text-overlay0 text-sm text-center">
          Voice mode requires microphone + audio context support.<br />
          Please use Chrome, Edge, or a modern browser.
        </p>
        <button onClick={onExit} className="text-green text-sm underline">Go back</button>
      </div>
    )
  }

  if (!connected) {
    return (
      <div className="flex flex-col h-full bg-crust items-center justify-center gap-4 px-6">
        <div className="w-3 h-3 rounded-full bg-yellow animate-pulse" />
        <p className="text-overlay0 text-sm">Connecting to Mayday...</p>
      </div>
    )
  }

  if (voice.micPermission === 'unknown') {
    return (
      <div className="flex flex-col h-full bg-crust items-center justify-center gap-4 px-6">
        <div className="w-3 h-3 rounded-full bg-green animate-pulse" />
        <p className="text-overlay0 text-sm">Requesting microphone access...</p>
      </div>
    )
  }

  if (voice.micPermission === 'denied') {
    return (
      <div className="flex flex-col h-full bg-crust items-center justify-center gap-4 px-6">
        <p className="text-overlay0 text-sm text-center">
          Microphone access is required for voice mode.<br />
          Allow microphone access in your browser settings.
        </p>
        <button onClick={onExit} className="text-green text-sm underline">Go back</button>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-crust relative">
      <div className="absolute top-0 left-0 right-0 z-10 p-3 sm:p-4 flex items-center justify-between">
        <button
          onClick={onExit}
          className="flex items-center gap-1.5 sm:gap-2 px-2 sm:px-3 py-1 rounded-full text-xs sm:text-sm text-overlay0 hover:text-text hover:bg-white/5 transition-colors"
        >
          <ArrowLeft className="h-3.5 sm:h-4 w-3.5 sm:w-4" />
          <span className="hidden sm:inline">Exit Voice</span>
        </button>
        {engine && (
          <div className="flex items-center gap-1.5 px-2 sm:px-3 py-1 rounded-full bg-white/5 text-[9px] sm:text-[10px] text-overlay1 uppercase tracking-wider">
            <Radio className="h-2.5 sm:h-3 w-2.5 sm:w-3" />
            {engine}
          </div>
        )}
      </div>

      <div className="flex-1 flex flex-col items-center justify-center px-4 sm:px-6 pb-16">
        {voice.state === 'idle' && voice.micPermission === 'granted' ? (
          <div className="flex flex-col items-center gap-4">
            <p className="text-overlay0 text-sm">Microphone ready</p>
            <button
              onClick={() => voice.start()}
              className="flex items-center gap-2 px-6 py-2 rounded-full bg-green/10 text-green text-sm border border-green/20 hover:bg-green/20 transition-colors"
            >
              <Mic className="h-4 w-4" />
              Start Listening
            </button>
          </div>
        ) : (
          <>
            <VoiceIndicator state={voice.state} />
            <div className="mt-6 min-h-[2rem] flex items-center justify-center">
              <VoiceTranscript text={voice.interimText} />
              {voice.state === 'listening' && !voice.interimText && (
                <p className="text-overlay0 text-xs animate-pulse">Speak now...</p>
              )}
            </div>
          </>
        )}

        {recentMessages.length > 0 && (
          <div className="mt-6 sm:mt-8 w-full max-w-lg mx-auto space-y-1 opacity-60 px-2 sm:px-0">
            <div className="border-t border-white/5 pt-2 sm:pt-3 mb-1 sm:mb-2">
              <span className="text-[9px] sm:text-[10px] uppercase tracking-widest text-overlay0">Recent</span>
            </div>
            {recentMessages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            {streaming && (
              <div className="flex justify-start my-1">
                <div className="bg-surface0/50 rounded-lg px-4 py-2.5">
                  <div className="flex gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" style={{ animationDelay: '150ms' }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-green animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </div>
  )
}
