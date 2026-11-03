import { useEffect, useState } from 'react'
import type { IssueRef } from '../../../src/integrations/issues'
import { laneName } from '../../../src/integrations/lane-name'
import type { NewLaneData } from '../../../src/ui/protocol'
import { ProviderAvatar } from '../components/provider-avatar'
import { onHostMessage, send } from '../host'

const VALID = /^[\w][\w./-]*$/
const SOURCE = { github: 'GitHub', linear: 'Linear' }

function Label({ children }: { children: string }) {
  return <div className="text-[11px] font-extrabold tracking-[0.08em] text-muted-foreground">{children}</div>
}

export function NewLaneApp() {
  const [data, setData] = useState<NewLaneData>()
  const [issues, setIssues] = useState<IssueRef[]>()
  const [notes, setNotes] = useState<string[]>([])
  const [issue, setIssue] = useState<IssueRef>()
  const [name, setName] = useState('')
  const [named, setNamed] = useState(false)
  const [repos, setRepos] = useState<string[]>([])
  const [lead, setLead] = useState('')
  const [ref, setRef] = useState('')
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const off = onHostMessage((message) => {
      if (message.type === 'newLane') {
        setData(message.data)
        setRepos(message.data.repos)
        setLead(message.data.roster.lead)
      }
      if (message.type === 'newLaneIssues') {
        setIssues((current) => [...message.issues, ...(current ?? []).filter((old) => !message.issues.some((found) => found.id === old.id))])
        if (message.notes.length > 0) setNotes(message.notes)
        const picked = message.issues.find((found) => found.id === message.pick)
        if (picked) setIssue(picked)
        setBusy(false)
      }
      if (message.type === 'newLaneError') {
        setError(message.message)
        setBusy(false)
      }
    })
    send({ type: 'ready' })
    return off
  }, [])
  // The branch follows the chosen issue until the user types their own.
  useEffect(() => {
    if (!named) setName(issue ? laneName(issue) : '')
  }, [issue, named])
  if (!data) return null
  const label = (id: string) => data.agents.find((agent) => agent.id === id)?.label ?? id
  const roster = [
    ...(data.roster.research ? [`Research ${label(data.roster.research)}`] : []),
    `Plan ${label(lead)}`,
    ...(data.roster.implement ? [`Implement ${label(data.roster.implement)}`] : []),
    ...(data.roster.review ? [`Review ${label(data.roster.review)}`] : [])
  ].join(' · ')
  const valid = VALID.test(name.trim()) && repos.length > 0 && Boolean(lead)
  const create = () => {
    if (!valid || busy) return
    setBusy(true)
    setError(undefined)
    send({ type: 'newLaneCreate', name: name.trim(), repos, lead, ...(issue ? { issue: { source: issue.source, id: issue.id } } : {}) })
  }
  return (
    <main className="flex min-h-screen items-center justify-center bg-page p-6 text-sm">
      <div role="dialog" aria-label="New worktree" data-card="" className="flex w-[620px] max-w-full flex-col gap-[18px] rounded-2xl bg-surface p-7 max-[520px]:p-5">
        <h1 className="text-[28px] font-extrabold tracking-[-0.02em]">New worktree</h1>
        <div>
          <Label>START FROM AN ISSUE (OPTIONAL)</Label>
          <div className="mt-2 flex flex-col gap-1.5">
            {issues === undefined ? <div className="text-muted-foreground">Looking for your issues…</div> : null}
            {(issues ?? []).map((candidate) => {
              const on = candidate.id === issue?.id
              return (
                <button
                  key={`${candidate.source}:${candidate.id}`}
                  type="button"
                  aria-pressed={on}
                  className={`flex min-h-12 items-center gap-2.5 rounded-[9px] border-2 bg-page px-3 text-left ${on ? 'border-foreground' : 'border-transparent'}`}
                  onClick={() => setIssue(on ? undefined : candidate)}
                >
                  <span className="shrink-0 font-mono text-xs font-semibold">{candidate.id}</span>
                  <span className="min-w-0 flex-1 truncate">{candidate.title}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">{SOURCE[candidate.source]}</span>
                </button>
              )
            })}
            <form
              className="flex gap-1.5"
              onSubmit={(event) => {
                event.preventDefault()
                if (!ref.trim()) return
                setBusy(true)
                setError(undefined)
                send({ type: 'newLaneFindIssue', ref })
                setRef('')
              }}
            >
              <input aria-label="Issue link or number" className="h-10 min-w-0 flex-1 rounded-lg bg-page px-3" placeholder="Paste an issue link, #482, or ENG-214" value={ref} onChange={(event) => setRef(event.target.value)} />
              <button type="submit" className="h-10 rounded-lg bg-control px-3 font-semibold" disabled={!ref.trim()}>
                Add
              </button>
            </form>
            {notes.map((note) => (
              <div key={note} className="text-xs text-muted-foreground">
                {note}{' '}
                {/Setup/.test(note) ? (
                  <button type="button" className="font-semibold text-foreground underline" onClick={() => send({ type: 'openSetup' })}>
                    Open Setup
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-[9px] bg-page p-3">
          <label htmlFor="lane-name" className="text-xs text-muted-foreground">
            Lane and branch
          </label>
          <input
            id="lane-name"
            className="mt-[3px] block w-full bg-transparent font-mono text-[15px] font-semibold outline-offset-2"
            placeholder="my-change"
            value={name}
            onChange={(event) => {
              setName(event.target.value)
              setNamed(event.target.value.length > 0)
            }}
          />
          {name.trim() && !VALID.test(name.trim()) ? <div className="mt-1.5 text-xs text-destructive">Letters, digits, and . _ / - only.</div> : null}
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[13px] text-muted-foreground">
            <span>Repos</span>
            {data.repos.map((repo) => {
              const on = repos.includes(repo)
              return (
                <button
                  key={repo}
                  type="button"
                  aria-pressed={on}
                  className={`h-7 rounded-md px-2 font-mono text-xs font-semibold ${on ? 'bg-primary text-primary-foreground' : 'bg-control text-foreground'}`}
                  onClick={() => setRepos(on ? repos.filter((other) => other !== repo) : [...repos, repo])}
                >
                  {repo}
                </button>
              )
            })}
          </div>
          <div className="mt-1.5 text-[13px] text-muted-foreground">
            A new worktree in each, warmed up automatically.{issue ? ` ${issue.id} seeds the lane's goal and notes.` : ''}
          </div>
        </div>
        <div>
          <Label>LEAD</Label>
          <div role="radiogroup" className="mt-2 grid grid-cols-[repeat(auto-fit,minmax(130px,1fr))] gap-2">
            {data.agents.map((agent) => {
              const on = agent.id === lead
              return (
                <button
                  key={agent.id}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  disabled={!agent.ready}
                  title={agent.ready ? undefined : `${agent.label} is not signed in`}
                  className={`flex h-[52px] items-center justify-center gap-2 rounded-[9px] border-2 bg-page font-bold disabled:opacity-40 ${on ? 'border-foreground' : 'border-transparent'}`}
                  onClick={() => setLead(agent.id)}
                >
                  <ProviderAvatar providerId={agent.id} className="size-[22px] rounded-md text-[11px]" />
                  {agent.label}
                </button>
              )
            })}
          </div>
          <div className="mt-2 text-[13px] text-muted-foreground">
            Roster: {roster}.{' '}
            <button type="button" className="font-semibold text-foreground underline" onClick={() => send({ type: 'openSetup' })}>
              Change
            </button>
          </div>
        </div>
        {error ? (
          <div role="alert" className="rounded-[9px] bg-destructive/10 px-3 py-2 text-destructive">
            {error}
          </div>
        ) : null}
        <button type="button" disabled={!valid || busy} className="h-[52px] rounded-[10px] bg-primary text-[15px] font-bold text-primary-foreground disabled:opacity-50" onClick={create}>
          {busy ? 'Working…' : 'Create and open chat'}
        </button>
      </div>
    </main>
  )
}
