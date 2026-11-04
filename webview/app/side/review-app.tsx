import { useEffect, useState } from 'react'
import type { ReviewData } from '../../../src/ui/protocol'
import { ProviderAvatar } from '../components/provider-avatar'
import { onHostMessage, persisted, send } from '../host'

type Run = ReviewData['delegations'][number]

const label = (value: string) => value.charAt(0).toUpperCase() + value.slice(1)

/** The first sentence of the report, or where the delegate is. */
function summary(run: Run): string {
  if (run.undone) return 'Undone'
  const first = run.report?.split('\n').find((line) => line.trim())?.trim()
  const sentence = first ? (/^(.+?[.!?])(\s|$)/.exec(first)?.[1] ?? first) : run.status === 'running' ? 'Working' : run.task
  const extra = [...(run.verify ? [run.verify.ok ? 'checks pass' : 'checks fail'] : []), ...(run.violations.length > 0 ? [`${run.violations.length} write${run.violations.length === 1 ? '' : 's'} blocked`] : [])]
  return extra.length > 0 ? `${sentence} ${label(extra.join(', '))}.` : sentence
}

function facts(run: Run): string {
  return [
    `${run.commands} ${run.commands === 1 ? 'command' : 'commands'}${run.failedCommands > 0 ? `, ${run.failedCommands} failed` : ''}`,
    ...(run.verify ? [`${run.verify.command} ${run.verify.ok ? 'passed' : 'failed'}`] : []),
    ...run.violations.map((violation) => `blocked: ${violation}`)
  ].join(' · ')
}

function lineTone(line: string): string {
  if (line.startsWith('+')) return 'bg-success/15'
  if (line.startsWith('-')) return 'bg-destructive/15'
  if (line.startsWith('@@')) return 'text-muted-foreground'
  return ''
}

function Changes({ run }: { run: Run }) {
  return (
    <section aria-label="Changes" data-card="" className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-xl bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-band px-3.5 py-3">
        <strong className="min-w-[10rem] flex-1 text-sm">
          {label(run.agent)}
          {run.role ? ` · ${label(run.role)}` : ''}
        </strong>
        {run.handoff ? (
          <button type="button" className="h-9 rounded-[7px] bg-band px-2.5 font-semibold" onClick={() => send({ type: 'viewHandoff', id: run.id })}>
            View handoff
          </button>
        ) : null}
        {run.files.length > 0 && !run.undone ? (
          <button type="button" className="h-9 rounded-[7px] bg-band px-2.5 font-semibold" onClick={() => send({ type: 'undoDelegation', id: run.id })}>
            Undo these changes
          </button>
        ) : null}
      </div>
      <div className="bg-page px-3.5 py-2.5 leading-[1.45]">
        <div className="whitespace-pre-wrap">{run.report ?? run.task}</div>
        <div className="mt-1 text-xs text-muted-foreground">Recorded by Canopy: {facts(run)}</div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-3.5 py-3 font-mono text-xs leading-[1.7]">
        {run.files.length === 0 ? <p className="font-sans text-muted-foreground">{run.undone ? 'These changes were undone.' : 'No file changes.'}</p> : null}
        {run.files.map((file) => (
          <div key={file.path} className="mb-3">
            <div className="mb-1 flex justify-between gap-3 rounded-md bg-band px-2 py-1.5 font-semibold">
              <span className="truncate">{file.path}</span>
              <span className="shrink-0">
                +{file.added} −{file.removed}
              </span>
            </div>
            <div className="overflow-x-auto">
              {file.lines.map((line, index) => (
                <div key={index} className={`px-2 whitespace-pre ${lineTone(line)}`}>
                  {line || ' '}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

export function ReviewApp() {
  const [data, setData] = useState<ReviewData>()
  const [selected, setSelected] = useState<string>()
  useEffect(() => {
    const off = onHostMessage((message) => {
      if (message.type === 'review') {
        setData(message.review)
        // VS Code restores this tab after a reload from the chat it reviews.
        persisted.set({ ...(persisted.get() as object | undefined), groupId: message.review.groupId })
      }
    })
    send({ type: 'ready' })
    return off
  }, [])
  if (!data) return null
  const run = data.delegations.find((candidate) => candidate.id === selected) ?? data.delegations.findLast((candidate) => candidate.files.length > 0) ?? data.delegations[0]
  const files = new Set(data.delegations.filter((candidate) => !candidate.undone).flatMap((candidate) => candidate.files.map((file) => file.path))).size
  const verify = data.delegations.findLast((candidate) => candidate.verify && !candidate.undone)?.verify
  return (
    <main className="flex h-screen flex-col bg-page text-[13px]">
      <div className="flex shrink-0 flex-wrap items-center gap-2.5 px-6 py-[18px]">
        <div className="min-w-[14rem] flex-1">
          <h1 className="truncate text-2xl font-extrabold tracking-[-0.02em]">Review: {data.title}</h1>
          <div className="mt-[3px] text-muted-foreground">
            {data.laneId ? <span className="font-mono">{data.laneId}</span> : 'No lane'} · {files} {files === 1 ? 'file' : 'files'}
            {verify ? ` · ${verify.command} ${verify.ok ? 'passed' : 'failed'}` : ''}
          </div>
        </div>
        {data.laneId && !data.inPrimary ? (
          <button type="button" className="h-11 rounded-[9px] bg-primary px-3.5 font-bold text-primary-foreground" onClick={() => send({ type: 'switchLane', laneId: data.laneId ?? '' })}>
            Run in primary checkout
          </button>
        ) : null}
        {data.laneId ? (
          <>
            <button type="button" className="h-11 rounded-[9px] bg-control px-3.5 font-semibold" onClick={() => send({ type: 'openLaneDiff' })}>
              All changes
            </button>
            <button type="button" className="h-11 rounded-[9px] bg-control px-3.5 font-semibold" onClick={() => send({ type: 'createPullRequest' })}>
              Create pull request
            </button>
          </>
        ) : null}
      </div>
      {data.delegations.length === 0 ? (
        <p className="px-6 text-muted-foreground">Nothing was handed out in this chat yet.</p>
      ) : (
        <div className="flex min-h-0 flex-1 gap-3 px-6 pb-6 max-[700px]:flex-col max-[700px]:overflow-auto">
          <section aria-label="Who did what" data-card="" className="w-[280px] shrink-0 overflow-auto rounded-xl bg-surface p-3.5 max-[700px]:w-full">
            <div className="text-[11px] font-extrabold tracking-[0.08em] text-muted-foreground">WHO DID WHAT</div>
            {data.delegations.map((candidate) => (
              <button
                key={candidate.id}
                type="button"
                aria-pressed={candidate.id === run?.id}
                className={`mt-2 flex w-full gap-2.5 rounded-[9px] border-2 bg-page p-2.5 text-left ${candidate.id === run?.id ? 'border-foreground' : 'border-transparent'}`}
                onClick={() => setSelected(candidate.id)}
              >
                <ProviderAvatar providerId={candidate.agent} className="size-6 rounded-[7px] text-[11px]" />
                <span className="min-w-0 flex-1">
                  <span className="block font-bold">
                    {label(candidate.agent)}
                    {candidate.role ? ` · ${label(candidate.role)}` : ''}
                  </span>
                  <span className={`mt-0.5 block leading-[1.35] ${candidate.verify && !candidate.verify.ok ? 'text-destructive' : 'text-muted-foreground'} ${candidate.undone ? 'line-through' : ''}`}>{summary(candidate)}</span>
                </span>
              </button>
            ))}
          </section>
          {run ? <Changes run={run} /> : null}
        </div>
      )}
    </main>
  )
}
