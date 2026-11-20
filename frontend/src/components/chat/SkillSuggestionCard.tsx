import { Lightbulb, X, Check } from 'lucide-react'

interface SkillSuggestionCardProps {
  name: string
  context: string
  onConfirm: () => void
  onDismiss: () => void
}

export function SkillSuggestionCard({ name, context, onConfirm, onDismiss }: SkillSuggestionCardProps) {
  return (
    <div className="pl-11">
      <div className="rounded-[20px] border border-green/30 bg-gradient-to-br from-green/[0.08] to-transparent p-4">
        <div className="flex items-start gap-3">
          <span className="w-8 h-8 shrink-0 rounded-xl bg-green/15 flex items-center justify-center">
            <Lightbulb className="w-4 h-4 text-green" />
          </span>
          <div className="flex-1 min-w-0">
            <p className="text-[11px] font-semibold text-green uppercase tracking-wider">Suggested skill</p>
            <p className="text-sm text-text mt-0.5">{name}</p>
            <p className="text-xs text-subtext0 leading-relaxed mt-1">{context}</p>
            <div className="flex gap-2 mt-3">
              <button type="button" onClick={onConfirm}
                      className="inline-flex items-center gap-1.5 rounded-xl bg-green text-black px-3 py-1.5 text-xs font-semibold hover:bg-green/90">
                <Check className="w-3.5 h-3.5" /> Use skill
              </button>
              <button type="button" onClick={onDismiss}
                      className="inline-flex items-center gap-1.5 rounded-xl bg-white/[0.06] text-subtext1 px-3 py-1.5 text-xs hover:bg-white/[0.1]">
                <X className="w-3.5 h-3.5" /> Not now
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
