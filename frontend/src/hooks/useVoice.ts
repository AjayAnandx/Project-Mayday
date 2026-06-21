import { useState, useRef, useCallback, useEffect } from 'react'

// Web Speech API types (not in standard DOM lib for this TS version)
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

declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognition
    webkitSpeechRecognition?: new () => SpeechRecognition
  }
}

export type VoiceState = 'idle' | 'listening' | 'processing' | 'speaking' | 'proactive'

interface UseVoiceOptions {
  sendMessage: (text: string) => void
}

const SUBMIT_SILENCE_MS = 1200
const PROACTIVE_SILENCE_MS = 15000

const PROACTIVE_PROMPTS = [
  "Hey, are you there?",
  "Hello? Need anything?",
  "Still here if you need me.",
  "Just checking in — need any help?",
  "Let me know if you need anything.",
  "I'm right here when you're ready.",
]

let lastPromptIdx = -1

function nextPrompt(): string {
  let i: number
  do { i = Math.floor(Math.random() * PROACTIVE_PROMPTS.length) }
  while (i === lastPromptIdx && PROACTIVE_PROMPTS.length > 1)
  lastPromptIdx = i
  return PROACTIVE_PROMPTS[i]
}

export function useVoice({ sendMessage }: UseVoiceOptions) {
  const [state, setState] = useState<VoiceState>('idle')
  const [interimText, setInterimText] = useState('')

  const isSupported = !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)

  const stateRef = useRef(state)
  stateRef.current = state

  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const proactiveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const transcriptRef = useRef('')

  const clearTimers = useCallback(() => {
    if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null }
    if (proactiveTimerRef.current) { clearTimeout(proactiveTimerRef.current); proactiveTimerRef.current = null }
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
      clearTimers()
      stopRecognition()
    }
  }, [sendMessage, clearTimers, stopRecognition])

  const startTimers = useCallback(() => {
    clearTimers()
    if (stateRef.current !== 'listening') return
    // Auto-recover: if mic was stopped (e.g. no-TTS response), restart it
    if (!recognitionRef.current) {
      startRef.current()
      return
    }
    silenceTimerRef.current = setTimeout(() => submitTranscript(), SUBMIT_SILENCE_MS)
    proactiveTimerRef.current = setTimeout(() => {
      if (stateRef.current !== 'listening') return
      const prompt = nextPrompt()
      setState('proactive')
      const u = new SpeechSynthesisUtterance(prompt)
      u.onstart = () => { if (stateRef.current !== 'idle') setState('proactive') }
      u.onend = () => { if (stateRef.current !== 'idle') { setState('listening'); startTimers() } }
      u.onerror = () => { if (stateRef.current !== 'idle') { setState('listening'); startTimers() } }
      speechSynthesis.speak(u)
    }, PROACTIVE_SILENCE_MS)
  }, [clearTimers, submitTranscript])

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

    if (cur === 'idle' || cur === 'processing') return

    // Interrupt speaking/proactive on any speech (user spoke while TTS was playing)
    if (cur === 'speaking' || cur === 'proactive') {
      speechSynthesis.cancel()
      transcriptRef.current = ''
      setInterimText('')
      stateRef.current = 'listening'
      setState('listening')
      return  // Discard this utterance (mixed with TTS echo) — user repeats after TTS stops
    }

    setInterimText(interim || transcriptRef.current + final)
    if (final) transcriptRef.current += final

    startTimers()
  }, [startTimers])

  const start = useCallback(() => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) { console.warn('SpeechRecognition not supported (try Chrome/Edge)'); return }

    const recognition = new SR()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'
    recognition.onresult = onResult
    recognition.onend = () => { if (stateRef.current !== 'idle') recognition.start() }
    recognition.onerror = (e: SpeechRecognitionErrorEvent) => {
      if (e.error === 'not-allowed' || e.error === 'aborted' || e.error === 'audio-capture') {
        setState('idle')
      }
    }

    recognitionRef.current = recognition
    transcriptRef.current = ''
    setInterimText('')
    recognition.start()
    setState('listening')
    startTimers()
  }, [onResult, startTimers])

  const startRef = useRef(start)
  startRef.current = start

  const stop = useCallback(() => {
    clearTimers()
    speechSynthesis.cancel()
    stopRecognition()
    transcriptRef.current = ''
    setInterimText('')
    setState('idle')
  }, [clearTimers, stopRecognition])

  const restartMic = useCallback(() => {
    // Only restart if mic was stopped (recognitionRef is null) and we're supposed to be listening
    if (!recognitionRef.current && stateRef.current !== 'idle') {
      startRef.current()
    }
  }, [])

  const speak = useCallback((text: string) => {
    if (!text.trim() || stateRef.current === 'idle') return
    speechSynthesis.cancel()
    // Restart mic before TTS so user can interrupt (submitTranscript killed it)
    restartMic()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.onstart = () => { if (stateRef.current !== 'idle') setState('speaking') }
    utterance.onend = () => {
      if (stateRef.current !== 'idle') {
        setState('listening')
        setInterimText('')
        restartMic()
        startTimers()
      }
    }
    utterance.onerror = () => {
      if (stateRef.current !== 'idle') { setState('listening'); restartMic(); startTimers() }
    }
    speechSynthesis.speak(utterance)
  }, [startTimers, restartMic])

  useEffect(() => {
    return () => {
      clearTimers()
      speechSynthesis.cancel()
      stopRecognition()
    }
  }, [clearTimers, stopRecognition])

  return { state, interimText, start, stop, speak, isSupported }
}
