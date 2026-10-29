import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import type { LaneInfo } from '../../../src/ui/protocol'
import { send } from '../host'
import { Codicon } from './codicon'

const NONE = ''

/** Which lane the chat is on: the lane decides where it may write and what its brief says. */
export function LanePicker({ lanes, current }: { lanes?: LaneInfo[]; current?: string }) {
  if (!lanes) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="xs" variant="ghost" className="min-w-0 text-muted-foreground" title={current ? `Lane: ${current}` : 'No lane'}>
          <Codicon name="git-branch" size={12} />
          <span className="hidden max-w-32 truncate @[26rem]:inline">{current ?? 'No lane'}</span>
          <Codicon name="chevron-down" size={12} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-w-80">
        <DropdownMenuRadioGroup
          value={current ?? NONE}
          onValueChange={(laneId) => send({ type: 'setLane', ...(laneId === NONE ? {} : { laneId }) })}
        >
          {lanes.map((lane) => (
            <DropdownMenuRadioItem key={lane.name} value={lane.name}>
              <span className="min-w-0 flex-1 truncate">{lane.name}</span>
              <span className="truncate text-xs text-muted-foreground">{lane.where}</span>
            </DropdownMenuRadioItem>
          ))}
          <DropdownMenuRadioItem value={NONE}>No lane</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => send({ type: 'newLane' })}>
          <Codicon name="add" size={12} />
          New lane…
        </DropdownMenuItem>
        {current && (
          <DropdownMenuItem onSelect={() => send({ type: 'reviewLane', laneId: current })}>
            <Codicon name="diff-multiple" size={12} />
            Review lane changes
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
