import type { SuggestionOptions } from '@tiptap/suggestion'
import { ReactRenderer } from '@tiptap/react'
import { forwardRef, useEffect, useImperativeHandle, useState } from 'react'
import { cn } from '@/lib/utils'

export type MenuItem = { id: string; label: string; description?: string }
type MenuProps = { items: MenuItem[]; command: (item: MenuItem) => void; heading: string; loading: boolean }
type MenuHandle = { onKeyDown: (event: KeyboardEvent) => boolean }

const SuggestionMenu = forwardRef<MenuHandle, MenuProps>(function SuggestionMenu({ items, command, heading, loading }, ref) {
  const [active, setActive] = useState(0)
  useEffect(() => setActive(0), [items])
  useImperativeHandle(
    ref,
    () => ({
      onKeyDown: (event) => {
        if (items.length === 0) return false
        if (event.key === 'ArrowDown') setActive((index) => (index + 1) % items.length)
        else if (event.key === 'ArrowUp') setActive((index) => (index + items.length - 1) % items.length)
        else if (event.key === 'Enter' || event.key === 'Tab') command(items[active])
        else return false
        return true
      }
    }),
    [items, active, command]
  )
  return (
    <div className="z-50 w-80 overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md">
      <div className="border-b px-2 py-1 text-[11px] text-muted-foreground">{heading}</div>
      {items.length === 0 ? (
        <div className="px-2 py-2 text-xs text-muted-foreground">{loading ? 'Searching…' : 'No matches'}</div>
      ) : (
        <ul className="max-h-64 overflow-auto py-1">
          {items.map((item, index) => (
            <li key={item.id}>
              <button
                type="button"
                className={cn('flex w-full flex-col items-start px-2 py-1 text-left text-xs', index === active && 'bg-accent')}
                onMouseEnter={() => setActive(index)}
                onMouseDown={(event) => {
                  event.preventDefault()
                  command(item)
                }}
              >
                <span className="max-w-full truncate font-medium">{item.label}</span>
                {item.description && <span className="line-clamp-1 text-muted-foreground">{item.description}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
})

/** Renders a TipTap suggestion as a floating menu; TipTap's mount() keeps it anchored to the cursor. */
export function renderMenu(heading: string): SuggestionOptions<MenuItem>['render'] {
  return () => {
    let renderer: ReactRenderer<MenuHandle, MenuProps> | undefined
    let unmount: (() => void) | undefined
    return {
      onStart: (props) => {
        renderer = new ReactRenderer(SuggestionMenu, {
          props: { items: props.items, command: props.command, heading, loading: props.loading },
          editor: props.editor
        })
        unmount = props.mount(renderer.element as HTMLElement)
      },
      onUpdate: (props) => renderer?.updateProps({ items: props.items, command: props.command, heading, loading: props.loading }),
      onKeyDown: ({ event }) => renderer?.ref?.onKeyDown(event) ?? false,
      onExit: () => {
        unmount?.()
        renderer?.destroy()
      }
    }
  }
}
