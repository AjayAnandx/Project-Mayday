import { Lightbulb, X, Check } from 'lucide-react'

interface SkillSuggestionCardProps {
  name: string
  context: string
  onConfirm: () => void
  onDismiss: () => void
}

export function SkillSuggestionCard({ name, context, onConfirm, onDismiss }: SkillSuggestionCardProps) {
  return (
    <div className="flex justify-start my-2">
      <div className="max-w-[80%] bg-surface0/60 rounded-2xl border border-green/30 p-4">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex-shrink-0 w-8 h-8 rounded-full bg-green/15 flex items-center justify-center">
            <Lightbulb className="w-4 h-4 text-green" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-green uppercase tracking-wider mb-1">
              Suggested Skill: {name}
            </p>
            <p className="text-sm text-subtext0 leading-relaxed">{context}</p>
            <div className="flex gap-2 mt-3">
              <button
                type="button"
                onClick={onConfirm}
                className="inline-flex items-center gap-1.5 rounded-full bg-green/15 text-green px-4 py-1.5 text-xs font-medium hover:bg-green/25 transition-colors"
              >
                <Check className="w-3 h-3" />
                Use Skill
              </button>
              <button
                type="button"
                onClick={onDismiss}
                className="inline-flex items-center gap-1.5 rounded-full bg-surface1/50 text-overlay1 px-4 py-1.5 text-xs font-medium hover:bg-surface1 transition-colors"
              >
                <X className="w-3 h-3" />
                Dismiss
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
