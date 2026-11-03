import { type ReactNode, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import type { SetupData } from '../../../src/ui/protocol'
import { ProviderAvatar } from '../components/provider-avatar'
import { onHostMessage, send } from '../host'

const ROLES = [
  { role: 'lead', label: 'Lead', hint: 'Talks with you, plans, and hands work out' },
  { role: 'research', label: 'Research', hint: 'Reads code and docs; never edits' },
  { role: 'implement', label: 'Implement', hint: 'The only agent that edits code when roles are enforced' },
  { role: 'review', label: 'Review', hint: 'Reads the diff and reports; never edits' }
] as const

const AGENT_STATUS: Record<string, { label: string; tone: string }> = {
  'signed-in': { label: 'Ready', tone: 'text-success' },
  'signed-out': { label: 'Needs sign-in', tone: 'text-warning' },
  'not-installed': { label: 'Not installed', tone: 'text-muted-foreground' },
  unknown: { label: 'Checking', tone: 'text-muted-foreground' }
}

function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg bg-muted p-4">
      <header className="mb-3 flex items-center gap-2">
        <h2 className="flex-1 text-sm font-semibold">{title}</h2>
        {action}
      </header>
      {children}
    </section>
  )
}

function Verify({ value }: { value: string }) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  return (
    <input
      aria-label="Verify command"
      className="h-8 w-full rounded-md border bg-background px-2 font-mono text-xs"
      placeholder="pnpm test"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => draft !== value && send({ type: 'setRoster', role: 'verify', value: draft.trim() })}
    />
  )
}

export function SetupApp() {
  const [data, setData] = useState<SetupData>()
  useEffect(() => {
    const off = onHostMessage((message) => {
      if (message.type === 'setup') setData(message.setup)
    })
    send({ type: 'ready' })
    return off
  }, [])
  if (!data) return null
  const ready = data.agents.filter((agent) => agent.status === 'signed-in')
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 p-6 text-[13px]">
      <h1 className="text-lg font-semibold">Setup</h1>
      <Panel title="Agents" action={<Button size="sm" variant="secondary" onClick={() => send({ type: 'manageAgents' })}>Sign in or install</Button>}>
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-2">
          {data.agents.map((agent) => {
            const status = AGENT_STATUS[agent.status] ?? AGENT_STATUS.unknown
            return (
              <li key={agent.id} className="flex items-center gap-2 rounded-md bg-background px-2 py-2">
                <ProviderAvatar providerId={agent.id} className="size-6 text-[11px]" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{agent.label}</span>
                  <span className={`block truncate text-xs ${status.tone}`}>{agent.account ?? status.label}</span>
                </span>
              </li>
            )
          })}
        </ul>
      </Panel>
      <Panel title="Who does what">
        <p className="mb-3 text-xs text-muted-foreground">New group chats start with this roster. The lead hands each kind of work to the agent you set, without being asked.</p>
        <div className="space-y-2">
          {ROLES.map(({ role, label, hint }) => (
            <label key={role} className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="w-24 shrink-0 font-medium">{label}</span>
              <select
                className="h-8 w-40 rounded-md border bg-background px-2"
                value={data.roster[role]}
                onChange={(event) => send({ type: 'setRoster', role, value: event.target.value })}
              >
                {role === 'lead' ? null : <option value="">Nobody</option>}
                {data.agents.map((agent) => (
                  <option key={agent.id} value={agent.id} disabled={agent.status !== 'signed-in' && agent.id !== data.roster[role]}>
                    {agent.label}
                  </option>
                ))}
              </select>
              <span className="min-w-[12rem] flex-1 text-xs text-muted-foreground">{hint}</span>
            </label>
          ))}
          <label className="flex items-center gap-3 pt-1">
            <input type="checkbox" checked={data.roster.enforce} onChange={(event) => send({ type: 'setEnforce', value: event.target.checked })} />
            <span>Enforce roles: AgentDeck blocks edits from every agent but Implement, and flags any that slip through.</span>
          </label>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-1">
            <span className="w-24 shrink-0 font-medium">Verify</span>
            <span className="min-w-[12rem] flex-1">
              <Verify value={data.roster.verify} />
              <span className="mt-1 block text-xs text-muted-foreground">AgentDeck runs this itself after Implement changes files, and reports the result to the lead.</span>
            </span>
          </div>
        </div>
        {ready.length === 0 ? <p className="mt-3 text-xs text-warning">No agent is signed in yet.</p> : null}
      </Panel>
      {data.workspace ? (
        <Panel title="Workspace" action={<Button size="sm" variant="secondary" onClick={() => send({ type: 'editWorkspaceConfig' })}>Edit config.toml</Button>}>
          <ul className="mb-3 space-y-1">
            {data.workspace.repos.map((repo) => (
              <li key={repo.name} className="flex items-baseline gap-2">
                <span className="font-medium">{repo.name}</span>
                <span className="text-xs text-muted-foreground">base {repo.base ?? 'unknown'}</span>
                {repo.setup ? <span className="truncate font-mono text-xs text-muted-foreground">setup: {repo.setup}</span> : null}
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">
            New lanes start {data.workspace.worktrees ? 'in worktrees' : 'in the primary checkout'}. Up to {data.workspace.maxSlots} worktrees per repo. Copied into new worktrees: {data.workspace.envFiles.join(', ') || 'nothing'}.
          </p>
        </Panel>
      ) : null}
      <Panel title="Issues">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <span className="w-24 shrink-0 font-medium">GitHub</span>
            <span className={`flex-1 text-xs ${data.github === 'signed-in' ? 'text-success' : 'text-muted-foreground'}`}>
              {data.github === 'signed-in' ? 'Connected through your gh login' : data.github === 'missing' ? 'Install the GitHub CLI (gh) to start lanes from issues and open pull requests' : 'Run gh auth login in a terminal'}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="w-24 shrink-0 font-medium">Linear</span>
            <span className={`flex-1 text-xs ${data.linear ? 'text-success' : 'text-muted-foreground'}`}>{data.linear ? 'Connected with an API key' : 'Not connected'}</span>
            {data.linear ? (
              <Button size="sm" variant="ghost" onClick={() => send({ type: 'disconnectLinear' })}>Disconnect</Button>
            ) : (
              <Button size="sm" variant="secondary" onClick={() => send({ type: 'connectLinear' })}>Add API key</Button>
            )}
          </div>
        </div>
      </Panel>
    </div>
  )
}
