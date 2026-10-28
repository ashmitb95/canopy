import { cn } from '@/lib/utils'

/** codicon.css is unlayered and beats Tailwind's text-size utilities, so size goes inline. */
export function Codicon({
  name,
  size = 14,
  spin = false,
  className
}: {
  name: string
  size?: number
  spin?: boolean
  className?: string
}) {
  return (
    <i
      aria-hidden
      className={cn('codicon', `codicon-${name}`, spin && 'codicon-modifier-spin', className)}
      style={{ fontSize: size }}
    />
  )
}
