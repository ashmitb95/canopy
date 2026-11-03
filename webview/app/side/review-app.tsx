import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import type { ReviewData } from '../../../src/ui/protocol'
import { Codicon } from '../components/codicon'
import { ProviderAvatar } from '../components/provider-avatar'
import { onHostMessage, send } from '../host'

type Run = ReviewData['delegations'][number]

function summary(run: Run): string {
  if (run.undone) return 'Undone'
  const parts = [
    run.files.length > 0 ? `${run.files.length} ${run.files.length === 1 ? 'file' : 'files'} changed` : 'No file changes',
    ...(run.verify ? [run.verify.ok ? 'checks pass' : 'checks fail'] : []),
    ...(run.violations.length > 0 ? [`${run.violations.length} blocked`] : [])
  ]
  return parts.join(' · ')
}

function lineTone(line: string): string {
  if (line.startsWith('+')) return 'bg-success/15'
  if (line.startsWith('-')) return 'bg-destructive/15'
  if (line.startsWith('@@')) return 'text-muted-foreground'
  return ''
}

function Detail({ run }: { run: Run }) {
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <header className="flex items-start gap-3">
        <ProviderAvatar providerId={run.agent} className="size-8 text-sm" />
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold capitalize">
            {run.agent}
            {run.role ? <span className="font-normal text-muted-foreground"> · {run.role}</span> : null}
          </h2>
          <p className="text-xs text-muted-foreground">{run.task}</p>
        </div>
        {run.handoff ? (
          <Button size="sm" variant="ghost" onClick={() => send({ type: 'viewHandoff', id: run.id })}>
            View handoff
          </Button>
        ) : null}
        {run.files.length > 0 && !run.undone ? (
          <Button size="sm" variant="secondary" onClick={() => send({ type: 'undoDelegation', id: run.id })}>
            Undo these changes
          </Button>
        ) : null}
      </header>
      {run.report ? <p className="whitespace-pre-wrap rounded-md bg-muted p-3 leading-relaxed">{run.report}</p> : null}
      <div className="rounded-md bg-muted p-3 text-xs">
        <div className="mb-1 font-bold tracking-wider text-muted-foreground">RECORDED BY AGENTDECK</div>
        <ul className="space-y-0.5">
          <li>{run.commands} commands run{run.failedCommands > 0 ? `, ${run.failedCommands} failed` : ''}</li>
          {run.verify ? (
            <li className={run.verify.ok ? 'text-success' : 'text-destructive'}>
              <span className="font-mono">{run.verify.command}</span> {run.verify.ok ? 'passed' : 'failed'}
            </li>
          ) : null}
          {run.violations.map((violation) => (
            <li key={violation} className="text-warning">
              Blocked: {violation}
            </li>
          ))}
        </ul>
      </div>
      {run.files.map((file) => (
        <section key={file.path} className="overflow-hidden rounded-md border">
          <header className="flex items-center gap-2 bg-muted px-3 py-1.5 text-xs">
            <span className="min-w-0 flex-1 truncate font-mono font-medium">{file.path}</span>
            <span className="text-success">+{file.added}</span>
            <span className="text-destructive">−{file.removed}</span>
          </header>
          <pre className="overflow-x-auto py-1 font-mono text-xs leading-5">
            {file.lines.map((line, index) => (
              <div key={index} className={`px-3 ${lineTone(line)}`}>
                {line || ' '}
              </div>
            ))}
          </pre>
        </section>
      ))}
    </div>
  )
}

export function ReviewApp() {
  const [data, setData] = useState<ReviewData>()
  const [selected, setSelected] = useState<string>()
  useEffect(() => {
    const off = onHostMessage((message) => {
      if (message.type === 'review') setData(message.review)
    })
    send({ type: 'ready' })
    return off
  }, [])
  if (!data) return null
  const run = data.delegations.find((candidate) => candidate.id === selected) ?? data.delegations.findLast((candidate) => candidate.files.length > 0) ?? data.delegations[0]
  return (
    <div className="flex min-h-screen flex-col text-[13px]">
      <header className="flex flex-wrap items-center gap-2 border-b px-6 py-3">
        <h1 className="min-w-0 flex-1 truncate text-base font-semibold">Review: {data.title}</h1>
        {data.laneId ? (
          <>
            <Button size="sm" variant="ghost" onClick={() => send({ type: 'openLaneDiff' })}>
              <Codicon name="diff" /> All changes
            </Button>
            {data.inPrimary ? null : (
              <Button size="sm" variant="secondary" onClick={() => send({ type: 'switchLane', laneId: data.laneId ?? '' })}>
                Run in primary checkout
              </Button>
            )}
            <Button size="sm" onClick={() => send({ type: 'createPullRequest' })}>
              Create pull request
            </Button>
          </>
        ) : null}
      </header>
      {data.delegations.length === 0 ? (
        <p className="p-6 text-muted-foreground">Nothing was handed out in this chat yet.</p>
      ) : (
        <div className="grid flex-1 grid-cols-[minmax(220px,280px)_1fr] gap-6 p-6 max-[640px]:grid-cols-1">
          <nav aria-label="Who did what" className="flex flex-col gap-1">
            <div className="mb-1 text-[11px] font-bold tracking-wider text-muted-foreground">WHO DID WHAT</div>
            {data.delegations.map((candidate) => (
              <button
                key={candidate.id}
                type="button"
                aria-current={candidate.id === run?.id}
                className={`flex gap-2 rounded-md px-2 py-2 text-left hover:bg-accent ${candidate.id === run?.id ? 'bg-muted' : ''}`}
                onClick={() => setSelected(candidate.id)}
              >
                <ProviderAvatar providerId={candidate.agent} className="size-6 text-[11px]" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium capitalize">
                    {candidate.agent}
                    {candidate.role ? <span className="font-normal text-muted-foreground"> · {candidate.role}</span> : null}
                  </span>
                  <span className={`block truncate text-xs ${candidate.undone ? 'text-muted-foreground line-through' : candidate.verify && !candidate.verify.ok ? 'text-destructive' : 'text-muted-foreground'}`}>{summary(candidate)}</span>
                </span>
              </button>
            ))}
          </nav>
          {run ? <Detail run={run} /> : null}
        </div>
      )}
    </div>
  )
}
