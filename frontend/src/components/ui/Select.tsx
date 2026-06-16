import { SelectHTMLAttributes, forwardRef } from 'react'

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
  options: { value: string; label: string }[]
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, options, className = '', ...props }, ref) => {
    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label className="text-xs font-medium text-subtext0">{label}</label>
        )}
        <select
          ref={ref}
          className={`w-full rounded-xl bg-surface0/50 px-4 py-2.5 text-sm text-text border border-surface1 focus:border-green/50 focus:outline-none focus:ring-1 focus:ring-green/20 transition-all outline-none ${className}`}
          {...props}
        >
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>
    )
  },
)

Select.displayName = 'Select'
