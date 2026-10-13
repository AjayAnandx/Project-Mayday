import { useState, useRef, useCallback, useEffect } from 'react'
import type { VoiceState } from './useVoice'
import type { MicPermission } from './useBackendVoice'
import type { WsResponse } from '../types/chat'

export interface RealtimeStatus {
  ready: boolean
  enabled: boolean
  transport: string
  relay_only: boolean
  model: string
  voice: string
  fallback: string
  reason: string
}

interface UseRealtimeVoiceOptions {
  onWorkerEvent: (event: WsResponse) => void
  onUserTranscript?: (text: string) => void
}

// AudioWorklet processor, inlined via Blob URL so no extra build asset is needed.
// Captures mono float32, converts to PCM16, ships transferable buffers.
// Also ships frame RMS (0..1) so the main thread can do local barge-in
// detection while the mic is suppressed during TTS playback.
const PCM_WORKLET = `
class PcmCapture extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (ch && ch.length) {
      const pcm = new Int16Array(ch.length)
      let sum = 0
      for (let i = 0; i < ch.length; i++) {
        const s = Math.max(-1, Math.min(1, ch[i]))
        pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff
        sum += s * s
      }
      const rms = Math.sqrt(sum / ch.length)
      this.port.postMessage({ pcm, rms }, [pcm.buffer])
    }
    return true
  }
}
registerProcessor('pcm-capture', PcmCapture)
`

const SAMPLE_RATE = 24000 // OpenAI Realtime PCM16 native rate
// Half-duplex echo guard: while Mayday is speaking, mic frames are dropped
// so speakers can't loop back into server VAD. Tail keeps the gate closed
// briefly after audio.done drains the scheduled playback queue.
const SPEAK_TAIL_MS = 300
// Local barge-in: a loud close-mic frame while suppressed re-opens the mic.
// Speaker echo is normally much quieter than a user interrupting.
const BARGE_IN_RMS = 0.08

function b64ToInt16(b64: string): Int16Array {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new Int16Array(bytes.buffer)
}

export function useRealtimeVoice({ onWorkerEvent, onUserTranscript }: UseRealtimeVoiceOptions) {
  const [state, setState] = useState<VoiceState>('idle')
  const [interimText, setInterimText] = useState('')
  const [micPermission, setMicPermission] = useState<MicPermission>('unknown')
  const [status, setStatus] = useState<RealtimeStatus | null>(null)
  const [statusError, setStatusError] = useState('')

  const nav = typeof navigator !== 'undefined' ? (navigator as any) : undefined
  const isSupported = !!(
    nav?.mediaDevices?.getUserMedia &&
    typeof window !== 'undefined' &&
    (window.AudioContext || (window as any).webkitAudioContext)
  )

  const stateRef = useRef<VoiceState>('idle')
  stateRef.current = state
  const callbacksRef = useRef({ onWorkerEvent, onUserTranscript })
  callbacksRef.current = { onWorkerEvent, onUserTranscript }

  const wsRef = useRef<WebSocket | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const micCtxRef = useRef<AudioContext | null>(null)
  const playCtxRef = useRef<AudioContext | null>(null)
  const playTimeRef = useRef(0)
  const sourcesRef = useRef<AudioBufferSourceNode[]>([])
  // Echo guard: true while assistant audio is playing (mic frames dropped).
  const suppressMicRef = useRef(false)
  const speakTailRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const echoDroppedRef = useRef(0)
  const lastAssistantRef = useRef('')

  // Fetch realtime readiness on mount (text-only fallback when not ready).
  useEffect(() => {
    let cancelled = false
    fetch('/api/realtime/status')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((s: RealtimeStatus) => {
        if (!cancelled) setStatus(s)
      })
      .catch((e) => {
        if (!cancelled) setStatusError(`Realtime status check failed: ${e}`)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const sendControl = useCallback((obj: unknown) => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify(obj))
      } catch {
        /* ignore */
      }
    }
  }, [])

  // Close the mic gate when the assistant starts speaking and discard any
  // echo tail already buffered server-side.
  const markSpeaking = useCallback(() => {
    if (speakTailRef.current) {
      clearTimeout(speakTailRef.current)
      speakTailRef.current = null
    }
    if (!suppressMicRef.current) {
      suppressMicRef.current = true
      sendControl({ type: 'input_audio_buffer.clear' })
    }
  }, [sendControl])

  // Re-open the mic shortly after playback ends (tail drains queued audio).
  const markListeningSoon = useCallback(() => {
    if (speakTailRef.current) clearTimeout(speakTailRef.current)
    speakTailRef.current = setTimeout(() => {
      suppressMicRef.current = false
      speakTailRef.current = null
    }, SPEAK_TAIL_MS)
  }, [])

  const cancelPlayback = useCallback(() => {
    for (const src of sourcesRef.current) {
      try {
        src.stop()
      } catch {
        /* already stopped */
      }
    }
    sourcesRef.current = []
    if (playCtxRef.current) playTimeRef.current = playCtxRef.current.currentTime
  }, [])

  const playPcm16 = useCallback((audio: Int16Array) => {
    const ctx = playCtxRef.current
    if (!ctx || audio.length === 0) return
    const buf = ctx.createBuffer(1, audio.length, SAMPLE_RATE)
    const out = buf.getChannelData(0)
    for (let i = 0; i < audio.length; i++) out[i] = audio[i] / 0x8000
    const src = ctx.createBufferSource()
    src.buffer = buf
    src.connect(ctx.destination)
    const at = Math.max(playTimeRef.current, ctx.currentTime)
    src.start(at)
    playTimeRef.current = at + buf.duration
    sourcesRef.current.push(src)
    src.onended = () => {
      sourcesRef.current = sourcesRef.current.filter((s) => s !== src)
    }
  }, [])

  const teardown = useCallback(() => {
    if (speakTailRef.current) {
      clearTimeout(speakTailRef.current)
      speakTailRef.current = null
    }
    suppressMicRef.current = false
    echoDroppedRef.current = 0
    lastAssistantRef.current = ''
    if (wsRef.current) {
      try {
        wsRef.current.close()
      } catch {
        /* ignore */
      }
      wsRef.current = null
    }
    if (streamRef.current) {
      for (const t of streamRef.current.getTracks()) t.stop()
      streamRef.current = null
    }
    if (micCtxRef.current) {
      micCtxRef.current.close().catch(() => {})
      micCtxRef.current = null
    }
    if (playCtxRef.current) {
      playCtxRef.current.close().catch(() => {})
      playCtxRef.current = null
    }
    sourcesRef.current = []
    playTimeRef.current = 0
  }, [])

  const handleServerMessage = useCallback(
    (data: any) => {
      const t = data?.type as string | undefined
      if (!t) return
      switch (t) {
        case 'session_ready':
          suppressMicRef.current = false
          setState('listening')
          break
        case 'response.created':
          setInterimText('')
          // Assistant turn starting — pre-emptively gate the mic so the
          // first audio frames can't loop back into server VAD.
          markSpeaking()
          break
        // GA names are response.output_audio.* / response.output_audio_transcript.*;
        // pre-GA beta names (response.audio.*) kept as fallback.
        case 'response.output_audio.delta':
        case 'response.audio.delta':
          if (data.delta) {
            markSpeaking()
            setState('speaking')
            try {
              playPcm16(b64ToInt16(data.delta))
            } catch {
              /* ignore bad chunk */
            }
          }
          break
        case 'response.output_audio.done':
        case 'response.audio.done':
          if (stateRef.current === 'speaking') setState('listening')
          markListeningSoon()
          break
        case 'response.output_audio_transcript.delta':
        case 'response.audio_transcript.delta':
          if (typeof data.delta === 'string') setInterimText((p) => p + data.delta)
          break
        case 'response.output_audio_transcript.done':
        case 'response.audio_transcript.done':
          if (typeof data.transcript === 'string') {
            setInterimText(data.transcript)
            lastAssistantRef.current = data.transcript.slice(-500)
          }
          break
        case 'response.done':
          markListeningSoon()
          break
        case 'input_audio_buffer.speech_started':
          // Barge-in: user started talking — drop queued playback and
          // re-open the mic immediately.
          if (speakTailRef.current) {
            clearTimeout(speakTailRef.current)
            speakTailRef.current = null
          }
          suppressMicRef.current = false
          cancelPlayback()
          setState('listening')
          break
        case 'user_transcript':
          if (data.text) callbacksRef.current.onUserTranscript?.(data.text)
          break
        case 'echo_suppressed':
          // Server dropped a transcript that matched our own TTS output.
          break
        case 'tool_result':
          if (data.escalated) setState('processing')
          break
        case 'worker_progress':
          if (data.event) callbacksRef.current.onWorkerEvent(data.event as WsResponse)
          break
        case 'worker_started':
          setState('processing')
          break
        case 'worker_done':
        case 'worker_cancelled':
          if (stateRef.current === 'processing') setState('listening')
          break
        case 'session_ended':
          teardown()
          setState('idle')
          break
        case 'error':
          setState('idle')
          setStatusError(data.message || 'Realtime error — text-only fallback')
          break
        default:
          break
      }
    },
    [cancelPlayback, markListeningSoon, markSpeaking, playPcm16, teardown],
  )

  const start = useCallback(async () => {
    if (stateRef.current !== 'idle') return
    if (!status?.ready) {
      setStatusError(status ? `Realtime unavailable (${status.reason}) — text-only fallback` : 'Realtime status unknown — text-only fallback')
      return
    }
    setStatusError('')
    setState('processing')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: SAMPLE_RATE,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      streamRef.current = stream
      setMicPermission('granted')
      suppressMicRef.current = false
      echoDroppedRef.current = 0

      const AC = window.AudioContext || (window as any).webkitAudioContext
      const micCtx = new AC({ sampleRate: SAMPLE_RATE })
      const playCtx = new AC({ sampleRate: SAMPLE_RATE })
      await micCtx.resume().catch(() => {})
      await playCtx.resume().catch(() => {})
      micCtxRef.current = micCtx
      playCtxRef.current = playCtx
      playTimeRef.current = playCtx.currentTime

      const blob = new Blob([PCM_WORKLET], { type: 'application/javascript' })
      const url = URL.createObjectURL(blob)
      try {
        await micCtx.audioWorklet.addModule(url)
      } finally {
        URL.revokeObjectURL(url)
      }
      const src = micCtx.createMediaStreamSource(stream)
      const node = new AudioWorkletNode(micCtx, 'pcm-capture')
      node.port.onmessage = (e: MessageEvent) => {
        const msg = e.data as { pcm?: Int16Array; rms?: number } | Int16Array
        // Back-compat: older worklet posted bare Int16Array.
        const pcm = (msg as { pcm?: Int16Array }).pcm ?? (msg as Int16Array)
        const rms = (msg as { rms?: number }).rms ?? 0
        if (!pcm?.length) return
        if (wsRef.current?.readyState !== WebSocket.OPEN) return
        if (suppressMicRef.current) {
          // Local barge-in: loud close-mic speech re-opens the gate so the
          // user can interrupt; quiet speaker echo stays dropped.
          if (rms >= BARGE_IN_RMS) {
            if (speakTailRef.current) {
              clearTimeout(speakTailRef.current)
              speakTailRef.current = null
            }
            suppressMicRef.current = false
            cancelPlayback()
            setState('listening')
          } else {
            echoDroppedRef.current += 1
            return
          }
        }
        try {
          wsRef.current.send(pcm.buffer as ArrayBuffer)
        } catch {
          /* socket closing */
        }
      }
      src.connect(node)

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${protocol}//${window.location.host}/api/realtime/voice`)
      wsRef.current = ws
      ws.onmessage = (ev) => {
        try {
          handleServerMessage(JSON.parse(ev.data))
        } catch {
          /* ignore malformed */
        }
      }
      ws.onclose = () => {
        if (wsRef.current === ws) {
          wsRef.current = null
          teardown()
          if (stateRef.current !== 'idle') setState('idle')
        }
      }
      ws.onerror = () => {
        setStatusError('Realtime connection error — text-only fallback')
      }
    } catch (e: any) {
      teardown()
      if (e?.name === 'NotAllowedError') {
        setMicPermission('denied')
      }
      setState('idle')
      setStatusError(e?.message || 'Could not start realtime voice')
    }
  }, [handleServerMessage, status, teardown])

  const stop = useCallback(() => {
    teardown()
    setInterimText('')
    setState('idle')
  }, [teardown])

  useEffect(() => {
    return () => {
      teardown()
    }
  }, [teardown])

  return { state, interimText, micPermission, status, statusError, isSupported, start, stop }
}
