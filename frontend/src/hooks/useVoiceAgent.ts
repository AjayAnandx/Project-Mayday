import { useEffect, useState, useCallback } from 'react'
import { useVoiceAgent as useCFVoiceAgent } from '@cloudflare/voice/react'
import type { VoiceState } from './useVoice'

export type MicPermission = 'unknown' | 'granted' | 'denied'

// Worker host. Set VITE_VOICE_WORKER_HOST in .env (e.g.
// mayday-voice-agent.your-subdomain.workers.dev) after `wrangler deploy`.
const VOICE_WORKER_HOST: string =
  (import.meta as any).env?.VITE_VOICE_WORKER_HOST ||
  'mayday-voice-agent.<your-subdomain>.workers.dev'

const VOICE_AGENT = 'MyAgent'

const STATUS_MAP: Record<string, VoiceState> = {
  idle: 'idle',
  listening: 'listening',
  thinking: 'processing',
  speaking: 'speaking',
}

/**
 * Bridges Cloudflare's `useVoiceAgent` (mic capture, STT, TTS, transport)
 * into the same shape the voice UI previously got from the local Web Speech
 * path, so VoiceMode keeps working without in-browser TTS.
 */
export function useVoiceAgent() {
  const cf = useCFVoiceAgent({
    agent: VOICE_AGENT,
    host: VOICE_WORKER_HOST,
    enabled: true,
  })

  const [state, setState] = useState<VoiceState>('idle')
  const [interimText, setInterimText] = useState('')
  const [micPermission, setMicPermission] = useState<MicPermission>('unknown')
  const [error, setError] = useState<string | null>(null)
  const transcript = cf.transcript ?? []

  useEffect(() => {
    setState(STATUS_MAP[cf.status] ?? 'idle')
  }, [cf.status])

  useEffect(() => {
    setInterimText(cf.interimTranscript ?? '')
  }, [cf.interimTranscript])

  useEffect(() => {
    if (cf.error) {
      setError(cf.error)
      if (/microphone|permission|NotAllowed|denied/i.test(cf.error)) {
        setMicPermission('denied')
      }
    }
  }, [cf.error])

  const start = useCallback(async () => {
    setError(null)
    try {
      await cf.startCall()
      setMicPermission('granted')
    } catch (e: any) {
      setError(e?.message || String(e))
    }
  }, [cf])

  const stop = useCallback(() => {
    cf.endCall()
  }, [cf])

  const toggleMute = useCallback(() => {
    cf.toggleMute()
  }, [cf])

  const isSupported =
    typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia

  return {
    state,
    interimText,
    transcript,
    start,
    stop,
    toggleMute,
    isMuted: cf.isMuted,
    isSupported,
    connected: cf.connected,
    micPermission,
    error,
    audioLevel: cf.audioLevel,
  }
}
