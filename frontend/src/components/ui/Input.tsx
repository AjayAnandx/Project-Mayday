import { InputHTMLAttributes, forwardRef } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, className = '', ...props }, ref) => {
    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label className="text-xs font-medium text-subtext0">{label}</label>
        )}
        <input
          ref={ref}
          className={`w-full rounded-xl bg-surface0/50 px-4 py-2.5 text-sm text-text placeholder-overlay0 border border-surface1 focus:border-green/50 focus:outline-none focus:ring-1 focus:ring-green/20 transition-all outline-none ${error ? 'border-red/50' : ''} ${className}`}
          {...props}
        />
        {error && <span className="text-xs text-red">{error}</span>}
      </div>
    )
  },
)

Input.displayName = 'Input'
