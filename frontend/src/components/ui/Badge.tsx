interface BadgeProps {
  children: string
  variant?: 'default' | 'high' | 'medium' | 'low' | 'success'
}

const variants: Record<string, string> = {
  default: 'bg-surface0 text-subtext0',
  high: 'bg-red/20 text-red',
  medium: 'bg-yellow/20 text-yellow',
  low: 'bg-green/20 text-green',
  success: 'bg-green/20 text-green',
}

export function Badge({ children, variant = 'default' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${variants[variant]}`}
    >
      {children}
    </span>
  )
}
