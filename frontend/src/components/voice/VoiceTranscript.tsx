interface VoiceTranscriptProps {
  text: string
}

export function VoiceTranscript({ text }: VoiceTranscriptProps) {
  if (!text) return null
  return (
    <p className="text-sm text-subtext0 text-center max-w-md leading-relaxed animate-in fade-in duration-300">
      {text}
    </p>
  )
}
