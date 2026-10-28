import { send } from '../host'
import { fileName } from '../format'
import { Codicon } from './codicon'

export function FilePill({
  path,
  range,
  label,
  onRemove
}: {
  path: string
  range?: [number, number]
  label?: string
  onRemove?: () => void
}) {
  return (
    <span className="inline-flex max-w-full items-center gap-1 rounded-md border bg-muted px-1.5 py-0.5 text-xs">
      <button
        type="button"
        title={path}
        className="inline-flex min-w-0 items-center gap-1 hover:underline"
        onClick={() => send({ type: 'openFile', path, line: range?.[0] })}
      >
        <Codicon name="file" size={12} />
        <span className="truncate">
          {label ?? fileName(path)}
          {range ? ` · L${range[0]}–${range[1]}` : ''}
        </span>
      </button>
      {onRemove && (
        <button
          type="button"
          aria-label="Remove file from the next message"
          className="text-muted-foreground hover:text-foreground"
          onClick={onRemove}
        >
          <Codicon name="close" size={12} />
        </button>
      )}
    </span>
  )
}
