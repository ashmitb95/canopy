import { cn } from '@/lib/utils'

const PROVIDERS: Record<string, { monogram: string; hue: string }> = {
  claude: { monogram: 'C', hue: '#B8603F' },
  codex: { monogram: 'X', hue: '#4F63C9' },
  grok: { monogram: 'G', hue: '#5B6670' },
  cursor: { monogram: 'R', hue: '#3F5C52' },
  opencode: { monogram: 'O', hue: '#6B5A3A' },
  gemini: { monogram: 'M', hue: '#2F6690' }
}

export function ProviderAvatar({ providerId, className }: { providerId: string; className?: string }) {
  const { monogram, hue } = PROVIDERS[providerId] ?? { monogram: providerId.slice(0, 1).toUpperCase(), hue: '#888888' }
  return (
    <span
      className={cn('inline-flex size-7 shrink-0 items-center justify-center rounded-md text-xs font-bold', className)}
      // Provider colors are the one color not taken from the theme: solid, with white letters, legible on light and dark.
      style={{ background: hue, color: '#FFFFFF' }}
    >
      {monogram}
    </span>
  )
}
