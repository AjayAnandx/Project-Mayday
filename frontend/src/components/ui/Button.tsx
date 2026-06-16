import { ButtonHTMLAttributes } from 'react'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
}

export function Button({
  variant = 'primary',
  size = 'md',
  className = '',
  children,
  ...props
}: ButtonProps) {
  const base = 'inline-flex items-center justify-center rounded-full font-medium transition-all focus:outline-none focus:ring-2 focus:ring-green/40 disabled:opacity-50 disabled:cursor-not-allowed'

  const variants = {
    primary: 'bg-green/15 text-green hover:bg-green/25',
    secondary: 'bg-surface1 text-subtext0 hover:bg-surface2 hover:text-text',
    ghost: 'text-subtext0 hover:text-text hover:bg-surface1',
    danger: 'bg-red/15 text-red hover:bg-red/25',
  }

  const sizes = {
    sm: 'px-3 py-1.5 text-xs',
    md: 'px-4 py-2 text-sm',
    lg: 'px-5 py-2.5 text-base',
  }

  return (
    <button
      className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}
