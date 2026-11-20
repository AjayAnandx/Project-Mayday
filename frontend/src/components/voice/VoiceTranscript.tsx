interface VoiceTranscriptProps {
  text: string
}

/** Live words as they're heard — large, centred, politely announced. */
export function VoiceTranscript({ text }: VoiceTranscriptProps) {
  if (!text) return null
  return (
    <p aria-live="polite" className="text-lg sm:text-xl text-text text-center max-w-xl leading-relaxed">
      “{text}”
    </p>
  )
}
