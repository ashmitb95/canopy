import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import type { PermissionMode } from '../../../src/core/types'
import { send } from '../host'
import { Codicon } from './codicon'

export const MODES: Record<PermissionMode, { label: string; icon: string }> = {
  ask: { label: 'Ask before edits', icon: 'shield' },
  'accept-edits': { label: 'Accept edits', icon: 'edit' },
  auto: { label: 'Auto', icon: 'sparkle' },
  plan: { label: 'Plan', icon: 'checklist' },
  'full-access': { label: 'Full access', icon: 'warning' }
}

export function ModePicker({ current, available }: { current: PermissionMode; available: readonly PermissionMode[] }) {
  if (available.length < 2) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="xs" variant="ghost" className="text-muted-foreground" title={MODES[current].label}>
          <Codicon name={MODES[current].icon} size={12} />
          <span className="hidden @[26rem]:inline">{MODES[current].label}</span>
          <span className="hidden @[26rem]:inline-flex"><Codicon name="chevron-down" size={12} /></span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuRadioGroup value={current} onValueChange={(mode) => send({ type: 'setMode', mode: mode as PermissionMode })}>
          {available.map((mode) => (
            <DropdownMenuRadioItem key={mode} value={mode}>
              <Codicon name={MODES[mode].icon} size={12} />
              {MODES[mode].label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
