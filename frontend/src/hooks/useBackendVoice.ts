import { useState, useRef, useCallback, useEffect } from 'react'
import type { VoiceState } from './useVoice'

const SUBMIT_SILENCE_MS = 1200
const TTS_ECHO_COOLDOWN_MS = 1500
const SENTENCE_RE = /^.*?[.!?](?:\s|$)/

interface SpeechRecognition extends EventTarget {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: SpeechRecognitionEvent) => void) | null
  onend: (() => void) | null
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null
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

interface UseVoiceOptions {
  sendMessage: (text: string) => void
}

export function useBackendVoice({ sendMessage }: UseVoiceOptions) {
  const [state, setState] = useState<VoiceState>('idle')
  const [interimText, setInterimText] = useState('')

  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  const isSupported = !!SR

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

  const clearTimers = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current)
      silenceTimerRef.current = null
    }
  }, [])

  const stopRecognition = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.onend = null
      try { recognitionRef.current.stop() } catch {}
      recognitionRef.current = null
    }
  }, [])

  const submitTranscript = useCallback(() => {
    const text = transcriptRef.current.trim()
    if (text) {
      transcriptRef.current = ''
      setInterimText('')
      sendMessage(text)
      setState('processing')
    }
  }, [sendMessage])

  const onResult = useCallback((event: SpeechRecognitionEvent) => {
    let interim = ''
    let final = ''
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const r = event.results[i]
      if (r.isFinal) final += r[0].transcript
      else interim += r[0].transcript
    }
    if (!interim && !final) return

    const cur = stateRef.current
    if (cur === 'idle' || cur === 'processing' || cur === 'speaking') return

    // Echo cooldown: discard speech within 1500ms after TTS ends
    if (cur === 'listening' && Date.now() - lastTtsEndRef.current < TTS_ECHO_COOLDOWN_MS) {
      return
    }

    setInterimText(interim || transcriptRef.current + final)
    if (final) transcriptRef.current += final

    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
    silenceTimerRef.current = setTimeout(() => submitTranscript(), SUBMIT_SILENCE_MS)
  }, [submitTranscript])

  const startRecognition = useCallback(() => {
    if (!SR) return
    stopRecognition()

    const recognition = new SR()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'
    recognition.onresult = onResult
    recognition.onend = () => {
      if (stateRef.current !== 'idle') {
        try { recognition.start() } catch {}
      }
    }
    recognition.onerror = (e: SpeechRecognitionErrorEvent) => {
      if (e.error === 'not-allowed' || e.error === 'aborted' || e.error === 'audio-capture') {
        setState('idle')
      }
    }

    recognitionRef.current = recognition
    recognition.start()
  }, [SR, onResult])

  const speakSentence = useCallback(async (text: string): Promise<void> => {
    const gen = genRef.current

    // Try Puter TTS
    const p = (window as any).puter
    if (p?.ai?.txt2speech) {
      try {
        const audioResult = await p.ai.txt2speech(text, {
          provider: "elevenlabs",
          voice: "21m00Tcm4TlvDq8ikWAM",
          model: "eleven_flash_v2_5",
        })
        if (gen !== genRef.current) return

        const url = audioResult instanceof Blob
          ? URL.createObjectURL(audioResult)
          : String(audioResult)

        const result = await new Promise<void>((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error('TTS timeout')), 15000)
          const el = new Audio(url)
          currentAudioRef.current = el
          el.onended = () => { clearTimeout(timeout); currentAudioRef.current = null; resolve() }
          el.onerror = () => { clearTimeout(timeout); currentAudioRef.current = null; reject(new Error('Audio playback error')) }
          el.play().catch(reject)
        })
        return
      } catch (e) {
        console.warn('Puter TTS failed, using fallback:', e)
      }
    }

    // Fallback to browser SpeechSynthesis
    return new Promise<void>((resolve) => {
      const u = new SpeechSynthesisUtterance(text)
      u.rate = 1.1
      const timeout = setTimeout(() => resolve(), 15000)
      u.onend = () => { clearTimeout(timeout); resolve() }
      u.onerror = () => { clearTimeout(timeout); resolve() }
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

  return { state, interimText, start, stop, feedTokens, flushTts, isSupported }
}
