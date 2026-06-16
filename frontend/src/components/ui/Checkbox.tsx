import { InputHTMLAttributes } from 'react'

interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: string
}

export function Checkbox({ label, className = '', ...props }: CheckboxProps) {
  return (
    <label className={`flex items-center gap-2.5 cursor-pointer ${className}`}>
      <input
        type="checkbox"
        className="w-4 h-4 rounded-md bg-surface0/50 border-surface1 text-green focus:ring-green/20 focus:ring-1 transition-all"
        {...props}
      />
      {label && <span className="text-sm text-text">{label}</span>}
    </label>
  )
}
