import { useState, useRef, useCallback, useEffect } from 'react'
import type { VoiceState } from './useVoice'

// Web Speech API types
interface SpeechRecognition extends EventTarget {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: SpeechRecognitionEvent) => void) | null
  onend: (() => void) | null
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null
  onstart: (() => void) | null
  start(): void
  stop(): void
}
interface SpeechRecognitionEvent extends Event {
  resultIndex: number
  results: SpeechRecognitionResultList
}
interface SpeechRecognitionErrorEvent extends Event {
  error: string
}

const SUBMIT_SILENCE_MS = 1200
const TTS_ECHO_COOLDOWN_MS = 1500
const SENTENCE_RE = /^.*?[.!?](?:\s|$)/

interface UseVoiceOptions {
  sendMessage: (text: string) => void
}

export type MicPermission = 'unknown' | 'granted' | 'denied'

export function useBackendVoice({ sendMessage }: UseVoiceOptions) {
  const [state, setState] = useState<VoiceState>('idle')
  const [interimText, setInterimText] = useState('')
  const [micPermission, setMicPermission] = useState<MicPermission>('unknown')

  const isSupported = !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)

  const stateRef = useRef(state)
  stateRef.current = state

  // TTS state
  const genRef = useRef(0)
  const ttsTextRef = useRef('')
  const ttsQueueRef = useRef<string[]>([])
  const utteranceCountRef = useRef(0)
  const currentAudioRef = useRef<HTMLAudioElement | null>(null)

  // STT state
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const transcriptRef = useRef('')
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastTtsEndRef = useRef(0)
  const lastSentTextRef = useRef('')
  const isSendingRef = useRef(false)

  const clearTimers = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current)
      silenceTimerRef.current = null
    }
  }, [])

  const stopRecognition = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.onend = null
      recognitionRef.current.onerror = null
      try { recognitionRef.current.stop() } catch {}
      recognitionRef.current = null
    }
  }, [])

  const submitTranscript = useCallback(() => {
    if (isSendingRef.current) return
    const text = transcriptRef.current.trim()
    if (!text) return
    if (text === lastSentTextRef.current) return

    lastSentTextRef.current = text
    isSendingRef.current = true
    transcriptRef.current = ''
    setInterimText('')
    clearTimers()
    stopRecognition()
    sendMessage(text)
    setState('processing')
  }, [sendMessage, clearTimers, stopRecognition])

  const startRecognition = useCallback(() => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) return

    const recognition = new SR()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'

    recognition.onstart = () => {
      setMicPermission('granted')
    }

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      if (recognitionRef.current !== recognition) return
      const now = Date.now()
      if (now - lastTtsEndRef.current < TTS_ECHO_COOLDOWN_MS) return

      let interim = ''
      let final = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const r = event.results[i]
        if (r.isFinal) final += r[0].transcript
        else interim += r[0].transcript
      }
      if (!interim && !final) return

      const cur = stateRef.current
      if (cur === 'idle' || cur === 'processing') return

      // User spoke while TTS was playing — interrupt
      if (cur === 'speaking') {
        genRef.current++
        if (currentAudioRef.current) {
          currentAudioRef.current.pause()
          currentAudioRef.current.src = ''
          currentAudioRef.current = null
        }
        speechSynthesis.cancel()
        ttsTextRef.current = ''
        ttsQueueRef.current = []
        utteranceCountRef.current = 0
        transcriptRef.current = ''
        setInterimText('')
        stateRef.current = 'listening'
        setState('listening')
        // Re-start recognition (may have stopped during TTS)
        startRecognition()
        return
      }

      setInterimText(interim || transcriptRef.current + final)
      if (final) transcriptRef.current += final

      clearTimers()
      silenceTimerRef.current = setTimeout(() => submitTranscript(), SUBMIT_SILENCE_MS)
    }

    recognition.onend = () => {
      if (recognitionRef.current !== recognition) return
      if (stateRef.current === 'listening') {
        try { recognition.start() } catch {}
      }
    }

    recognition.onerror = (e: SpeechRecognitionErrorEvent) => {
      if (e.error === 'not-allowed') {
        setMicPermission('denied')
        setState('idle')
      }
    }

    recognitionRef.current = recognition
    try { recognition.start() } catch {}
  }, [submitTranscript, clearTimers])

  const speakSentence = useCallback(async (text: string): Promise<void> => {
    const gen = genRef.current

    // Cancel any prior TTS before starting
    speechSynthesis.cancel()
    if (currentAudioRef.current) {
      currentAudioRef.current.pause()
      currentAudioRef.current.src = ''
      currentAudioRef.current = null
    }

    // Try Deepgram TTS
    try {
      const resp = await fetch('/api/voice/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      if (!resp.ok) throw new Error(`TTS HTTP ${resp.status}`)
      if (gen !== genRef.current) return

      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)

      await new Promise<void>((resolve, reject) => {
        const el = new Audio(url)
        currentAudioRef.current = el
        el.onended = () => { URL.revokeObjectURL(url); currentAudioRef.current = null; resolve() }
        el.onerror = () => { URL.revokeObjectURL(url); currentAudioRef.current = null; reject(new Error('Audio playback error')) }
        el.play().catch((err) => {
          URL.revokeObjectURL(url)
          currentAudioRef.current = null
          reject(err)
        })
      })
      return
    } catch (e) {
      console.warn('Deepgram TTS failed, using fallback:', e)
    }

    // Fallback to browser SpeechSynthesis
    speechSynthesis.cancel()
    await new Promise<void>((resolve) => {
      const u = new SpeechSynthesisUtterance(text)
      u.rate = 1.1
      u.onend = () => { resolve() }
      u.onerror = () => { resolve() }
      speechSynthesis.speak(u)
    })
  }, [])

  const speakNextSentence = useCallback(async () => {
    while (stateRef.current !== 'idle') {
      const text = ttsQueueRef.current.shift()
      if (!text) break
      utteranceCountRef.current++
      try {
        await speakSentence(text)
      } catch {
        /* continue */
      }
      if (utteranceCountRef.current > 0) {
        utteranceCountRef.current--
      }
    }
    if (utteranceCountRef.current <= 0 && stateRef.current !== 'idle') {
      isSendingRef.current = false
      lastTtsEndRef.current = Date.now()
      stateRef.current = 'listening'
      setState('listening')
      startRecognition()
    }
  }, [speakSentence, startRecognition])

  const processTtsTokens = useCallback((text: string) => {
    ttsTextRef.current += text
    while (true) {
      const m = ttsTextRef.current.match(SENTENCE_RE)
      if (!m) break
      const sentence = m[0].trim()
      ttsTextRef.current = ttsTextRef.current.slice(m[0].length)
      if (sentence) {
        ttsQueueRef.current.push(sentence)
        if (utteranceCountRef.current <= 0) {
          stateRef.current = 'speaking'
          setState('speaking')
          stopRecognition()
          speakNextSentence()
        }
      }
    }
  }, [speakNextSentence, stopRecognition])

  const flushTtsBuffer = useCallback(() => {
    const remaining = ttsTextRef.current.trim()
    ttsTextRef.current = ''
    if (remaining && stateRef.current !== 'idle') {
      ttsQueueRef.current.push(remaining)
      if (utteranceCountRef.current <= 0) {
        stateRef.current = 'speaking'
        setState('speaking')
        stopRecognition()
        speakNextSentence()
      }
    } else if (stateRef.current !== 'idle') {
      isSendingRef.current = false
      lastTtsEndRef.current = Date.now()
      stateRef.current = 'listening'
      setState('listening')
      startRecognition()
    }
  }, [speakNextSentence, startRecognition, stopRecognition])

  const cancelTts = useCallback(() => {
    genRef.current++
    if (currentAudioRef.current) {
      currentAudioRef.current.pause()
      currentAudioRef.current.src = ''
      currentAudioRef.current = null
    }
    speechSynthesis.cancel()
    ttsTextRef.current = ''
    ttsQueueRef.current = []
    utteranceCountRef.current = 0
  }, [])

  const start = useCallback(() => {
    transcriptRef.current = ''
    setInterimText('')
    startRecognition()
    stateRef.current = 'listening'
    setState('listening')
  }, [startRecognition])

  const stop = useCallback(() => {
    clearTimers()
    cancelTts()
    speechSynthesis.cancel()
    stopRecognition()
    transcriptRef.current = ''
    setInterimText('')
    lastSentTextRef.current = ''
    isSendingRef.current = false
    setState('idle')
  }, [clearTimers, cancelTts, stopRecognition])

  const feedTokens = useCallback((text: string) => {
    if (stateRef.current !== 'idle') processTtsTokens(text)
  }, [processTtsTokens])

  const flushTts = useCallback(() => {
    if (stateRef.current !== 'idle') flushTtsBuffer()
  }, [flushTtsBuffer])

  useEffect(() => {
    return () => {
      clearTimers()
      cancelTts()
      speechSynthesis.cancel()
      stopRecognition()
    }
  }, [clearTimers, cancelTts, stopRecognition])

  return { state, interimText, start, stop, feedTokens, flushTts, isSupported, micPermission }
}
