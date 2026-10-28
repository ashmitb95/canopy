import { cn } from '@/lib/utils'

const PROVIDERS: Record<string, { monogram: string; hue: string }> = {
  claude: { monogram: 'C', hue: '#d97757' },
  codex: { monogram: 'Cx', hue: '#10a37f' }
}

export function ProviderAvatar({ providerId, className }: { providerId: string; className?: string }) {
  const { monogram, hue } = PROVIDERS[providerId] ?? { monogram: providerId.slice(0, 1).toUpperCase(), hue: '#888888' }
  return (
    <span
      className={cn('inline-flex size-7 shrink-0 items-center justify-center rounded-md text-xs font-semibold', className)}
      // Provider tints are the one color not taken from the theme; mixing with the theme keeps them legible.
      style={{
        background: `color-mix(in srgb, ${hue} 22%, var(--background))`,
        color: `color-mix(in srgb, ${hue} 80%, var(--foreground))`
      }}
    >
      {monogram}
    </span>
  )
}
