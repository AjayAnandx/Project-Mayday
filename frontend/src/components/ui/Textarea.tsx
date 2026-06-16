import { TextareaHTMLAttributes, forwardRef } from 'react'
import { cn } from '../../lib/utils'

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, className, ...props }, ref) => (
    <div className="flex flex-col gap-1">
      {label && <label className="text-xs font-medium text-subtext0">{label}</label>}
      <textarea
        ref={ref}
        className={cn(
          'w-full resize-none bg-surface0/50 px-4 py-3 leading-[1.2] text-text placeholder:text-overlay0',
          'border-none outline-none focus-visible:ring-0 focus-visible:outline-none',
          className,
        )}
        {...props}
      />
    </div>
  ),
)
Textarea.displayName = 'Textarea'
