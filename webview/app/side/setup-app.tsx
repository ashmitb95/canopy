import { type ReactNode, useEffect, useState } from 'react'
import type { SetupData } from '../../../src/ui/protocol'
import { ProviderAvatar } from '../components/provider-avatar'
import { onHostMessage, send } from '../host'

const STEPS = ['Connect agents', 'Who does what', 'Workspace'] as const

const RAIL = [
  { title: ['One chat.', 'Every agent.'], text: 'Give each agent the work it does best, on your own accounts. AgentDeck moves the work between them.' },
  { title: ['Who does what.'], text: 'The lead talks with you and hands out work by this roster, without being asked. These are defaults, and any chat can change them.' },
  {
    title: ['Your code runs', 'in one place.'],
    text: "That's your primary checkout: the repo folder you cloned, with your env files and dev server. Other lanes wait in ready worktrees. Move any lane there to run it, on its own branch and with its uncommitted work."
  }
]

const ROLES = [
  { role: 'research', name: 'Research', use: 'Reads and reports. Never writes.' },
  { role: 'implement', name: 'Implement', use: 'The only role that edits code.' },
  { role: 'review', name: 'Review', use: 'Checks the work and reports. Never writes.' }
] as const

const PALETTES = [
  { id: 'paper', name: 'Paper', swatch: 'var(--vscode-foreground)' },
  { id: 'peach', name: 'Peach', swatch: '#FFB98A' },
  { id: 'lilac', name: 'Lilac', swatch: '#C9B4F5' },
  { id: 'sage', name: 'Sage', swatch: '#B5D6A0' },
  { id: 'sky', name: 'Sky', swatch: '#A6D2F5' },
  { id: 'theme', name: 'Theme', swatch: 'var(--vscode-button-background)' }
]

// The rail is the inverted primary color; its softer text is mixed from the two, so it holds in any theme.
const SOFT = { color: 'color-mix(in srgb, var(--primary-foreground) 80%, var(--primary))' }

function Logo() {
  return (
    <svg width="56" height="56" viewBox="0 0 24 24" role="img" aria-label="AgentDeck" className="shrink-0">
      <rect x="9" y="1" width="6" height="22" rx="2" fill="currentColor" />
      <rect x="15" y="5" width="8" height="4" rx="2" fill="currentColor" />
      <rect x="1" y="9" width="8" height="4" rx="2" fill="currentColor" />
      <rect x="15" y="16" width="8" height="4" rx="2" fill="currentColor" />
    </svg>
  )
}

/** A row of choices where exactly one is on. */
function Segments<T extends string>({ options, value, onPick, inverted, wide }: { options: { value: T; label: string; disabled?: boolean }[]; value: T; onPick: (value: T) => void; inverted?: boolean; wide?: boolean }) {
  return (
    <div role="radiogroup" className={`flex gap-1 rounded-[9px] p-1 ${inverted ? '' : 'bg-band'}`} style={inverted ? { background: 'color-mix(in srgb, var(--primary-foreground) 16%, var(--primary))' } : undefined}>
      {options.map((option) => {
        const on = option.value === value
        const fill = inverted ? (on ? 'bg-primary-foreground text-primary' : '') : on ? 'bg-primary text-primary-foreground' : ''
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={option.disabled}
            className={`h-[38px] rounded-md px-3 font-semibold disabled:opacity-40 ${wide ? 'flex-1' : ''} ${fill}`}
            onClick={() => onPick(option.value)}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div data-card="" className="rounded-xl bg-surface p-3.5">
      <div className="font-bold">{title}</div>
      {children}
    </div>
  )
}

function Field({ label, value, placeholder, onSave }: { label: string; value: string; placeholder?: string; onSave: (value: string) => void }) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  return (
    <label className="block min-w-[10rem] flex-1">
      <span className="mb-1 block text-xs text-muted-foreground">{label}</span>
      <input
        className="h-[38px] w-full rounded-lg bg-page px-2.5 font-mono"
        value={draft}
        placeholder={placeholder}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => draft !== value && onSave(draft)}
      />
    </label>
  )
}

function Agents({ data }: { data: SetupData }) {
  return (
    <>
      <h1 className="text-[28px] font-extrabold tracking-[-0.02em]">Connect your agents</h1>
      <p className="mt-1.5 text-muted-foreground">AgentDeck runs the CLIs you already have, and they keep their own sign-ins.</p>
      <div className="mt-6 flex flex-col gap-2">
        {data.agents.map((agent) => {
          const ready = agent.status === 'signed-in'
          const missing = agent.status === 'not-installed'
          const detail = missing ? `Install the ${agent.label} CLI to connect` : [agent.account ?? (ready ? `${agent.label} account` : 'Not signed in'), ...(agent.version ? [`CLI ${agent.version}`] : [])].join(' · ')
          return (
            <div key={agent.id} data-card="" className="flex min-h-[72px] flex-wrap items-center gap-3.5 rounded-xl bg-surface px-4 py-3">
              <ProviderAvatar providerId={agent.id} className="size-9 rounded-[9px] text-base" />
              <div className="min-w-[10rem] flex-1">
                <div className="text-[15px] font-bold">{agent.label}</div>
                <div className="mt-0.5 text-muted-foreground">{detail}</div>
              </div>
              <span className={`rounded-md px-2 py-1 text-xs font-bold ${ready ? 'bg-success/15 text-success' : missing ? 'bg-band text-muted-foreground' : 'bg-warning/15 text-warning'}`}>
                {ready ? 'Connected' : missing ? 'Not installed' : agent.status === 'unknown' ? 'Checking' : 'Signed out'}
              </span>
              <button
                type="button"
                className={`h-11 min-w-24 rounded-lg px-3 font-semibold ${ready ? 'bg-control' : 'bg-primary text-primary-foreground'}`}
                onClick={() => send(missing ? { type: 'installAgent', providerId: agent.id } : { type: 'manageAgents' })}
              >
                {ready ? 'Manage' : missing ? 'Install' : 'Sign in'}
              </button>
            </div>
          )
        })}
      </div>
      <button type="button" className="mt-2.5 h-10 self-start px-3 font-semibold underline" onClick={() => send({ type: 'addAgent' })}>
        Add another ACP agent
      </button>
    </>
  )
}

function Roster({ data }: { data: SetupData }) {
  const choices = (current: string, none: boolean) => [
    ...(none ? [{ value: '', label: 'Nobody' }] : []),
    ...data.agents.map((agent) => ({ value: agent.id, label: agent.label, disabled: agent.status !== 'signed-in' && agent.id !== current }))
  ]
  return (
    <div className="flex flex-col gap-3">
      <div data-card="primary" className="flex flex-wrap items-center gap-3 rounded-xl bg-primary p-4 text-primary-foreground">
        <div className="min-w-[12rem] flex-1">
          <div className="text-lg font-extrabold">Lead</div>
          <div className="mt-0.5" style={SOFT}>
            Starts each chat, plans with you, and hands out the rest.
          </div>
        </div>
        <Segments inverted options={choices(data.roster.lead, false)} value={data.roster.lead} onPick={(value) => send({ type: 'setRoster', role: 'lead', value })} />
      </div>
      <div data-card="" className="rounded-xl bg-surface px-4 py-1">
        {ROLES.map(({ role, name, use }) => (
          <div key={role} className="flex min-h-[68px] flex-wrap items-center gap-3 border-b border-band py-2 last:border-b-0">
            <div className="min-w-[12rem] flex-1">
              <div className="text-[15px] font-bold">{name}</div>
              <div className="mt-0.5 text-muted-foreground">{use}</div>
            </div>
            <Segments options={choices(data.roster[role], role !== 'implement')} value={data.roster[role]} onPick={(value) => send({ type: 'setRoster', role, value })} />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3">
        <Card title="Delegate questions">
          <div className="mt-2.5">
            <Segments
              wide
              options={[
                { value: 'lead', label: 'Lead first' },
                { value: 'user', label: 'Always me' }
              ]}
              value={data.roster.questionsTo}
              onPick={(value) => send({ type: 'setQuestionsTo', value })}
            />
          </div>
          <p className="mt-2 leading-[1.4] text-muted-foreground">{data.roster.questionsTo === 'lead' ? 'The lead answers from the chat. You can change any answer.' : 'Every question from a delegate comes to you.'}</p>
        </Card>
        <Card title="Permissions">
          <div className="mt-2.5 flex h-[42px] items-center rounded-lg bg-band px-2.5 font-semibold">Always you</div>
          <p className="mt-2 leading-[1.4] text-muted-foreground">A model never grants permission for you.</p>
        </Card>
        <Card title="Enforce roles">
          <button
            type="button"
            aria-pressed={data.roster.enforce}
            className={`mt-2.5 h-[42px] w-full rounded-lg font-bold ${data.roster.enforce ? 'bg-primary text-primary-foreground' : 'bg-band'}`}
            onClick={() => send({ type: 'setEnforce', value: !data.roster.enforce })}
          >
            {data.roster.enforce ? 'On' : 'Off'}
          </button>
          <p className="mt-2 leading-[1.4] text-muted-foreground">Only Implement can write. Others are blocked and told to delegate.</p>
        </Card>
      </div>
      <div data-card="" className="flex flex-wrap items-end gap-3 rounded-xl bg-surface p-3.5">
        <Field label="Verify: AgentDeck runs this itself after Implement changes files" value={data.roster.verify} placeholder="pnpm test" onSave={(value) => send({ type: 'setRoster', role: 'verify', value: value.trim() })} />
      </div>
    </div>
  )
}

function Workspace({ data }: { data: SetupData }) {
  const workspace = data.workspace
  return (
    <>
      <h1 className="text-[28px] font-extrabold tracking-[-0.02em]">Set up new worktrees</h1>
      <p className="mt-1.5 text-muted-foreground">{workspace ? `We found these repos in ${workspace.name}, and filled in what we could detect.` : 'Open a folder to set up worktrees.'}</p>
      {workspace ? (
        <div data-card="" className="mt-6 rounded-xl bg-surface px-4 py-1">
          {workspace.repos.map((repo) => (
            <div key={repo.name} className="flex flex-wrap items-end gap-3.5 border-b border-band py-3 last:border-b-0">
              <span className="w-20 shrink-0 pb-2.5 font-mono font-semibold">{repo.name}</span>
              <Field label="Setup command" value={repo.setup ?? ''} placeholder="pnpm install" onSave={(command) => send({ type: 'setRepoSetup', repo: repo.name, command })} />
              <Field label="Env files to copy" value={repo.envFiles.join(', ')} placeholder={workspace.envFiles.join(', ')} onSave={(value) => send({ type: 'setRepoEnvFiles', repo: repo.name, value })} />
            </div>
          ))}
        </div>
      ) : null}
      <div className="mt-3 grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-3">
        <div data-card="" className="rounded-xl bg-surface p-3.5">
          <div className="font-bold">Issues</div>
          <div className="text-muted-foreground">Start a lane from an issue. Optional.</div>
          <div className="mt-3 flex min-h-11 items-center gap-2">
            <span className="flex-1">
              GitHub ·{' '}
              <span className={data.github === 'signed-in' ? 'font-semibold text-success' : 'text-muted-foreground'}>
                {data.github === 'signed-in' ? 'via your gh login' : data.github === 'missing' ? 'install the GitHub CLI' : 'run gh auth login'}
              </span>
            </span>
          </div>
          <div className="flex min-h-11 items-center gap-2">
            <span className="flex-1">
              Linear{data.linear ? <span className="font-semibold text-success"> · connected</span> : null}
            </span>
            <button
              type="button"
              className={`h-10 rounded-lg px-3 font-bold ${data.linear ? 'bg-control' : 'bg-primary text-primary-foreground'}`}
              onClick={() => send({ type: data.linear ? 'disconnectLinear' : 'connectLinear' })}
            >
              {data.linear ? 'Disconnect' : 'Add API key'}
            </button>
          </div>
        </div>
        <div data-card="" className="rounded-xl bg-surface p-3.5">
          <div className="font-bold">Colours</div>
          <div className="text-muted-foreground">Backgrounds and borders follow your VS Code theme.</div>
          <div role="radiogroup" className="mt-3 grid grid-cols-3 gap-1.5">
            {PALETTES.map((palette) => (
              <button
                key={palette.id}
                type="button"
                role="radio"
                aria-checked={data.palette === palette.id}
                className={`flex h-10 items-center gap-2 rounded-lg border-2 bg-band px-2.5 font-semibold ${data.palette === palette.id ? 'border-foreground' : 'border-transparent'}`}
                onClick={() => send({ type: 'setPalette', value: palette.id })}
              >
                <span className="size-3.5 shrink-0 rounded" style={{ background: palette.swatch }} />
                {palette.name}
              </button>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}

export function SetupApp() {
  const [data, setData] = useState<SetupData>()
  const [step, setStep] = useState(0)
  useEffect(() => {
    const off = onHostMessage((message) => {
      if (message.type === 'setup') setData(message.setup)
    })
    send({ type: 'ready' })
    return off
  }, [])
  if (!data) return null
  const connected = data.agents.filter((agent) => agent.status === 'signed-in').length
  const rail = RAIL[step]
  return (
    <div className="flex min-h-screen bg-page text-sm max-[760px]:flex-col">
      <aside data-card="primary" className="flex w-[380px] shrink-0 flex-col bg-primary p-10 text-primary-foreground max-[1000px]:w-[300px] max-[1000px]:p-7 max-[760px]:w-full">
        {step === 0 ? <Logo /> : null}
        <div className={`text-[40px] leading-[1.05] font-extrabold tracking-[-0.03em] max-[1000px]:text-[32px] ${step === 0 ? 'mt-7' : ''}`}>
          {rail.title.map((line) => (
            <div key={line}>{line}</div>
          ))}
        </div>
        <p className="mt-3.5 leading-normal" style={SOFT}>
          {rail.text}
        </p>
        <nav aria-label="Setup steps" className="mt-auto flex flex-col gap-2.5 pt-8 max-[760px]:flex-row max-[760px]:flex-wrap">
          {STEPS.map((name, index) => (
            <button
              key={name}
              type="button"
              aria-current={index === step ? 'step' : undefined}
              className={`flex h-10 items-center rounded-lg px-3 text-left ${index === step ? 'bg-primary-foreground font-bold text-primary' : ''}`}
              style={index === step ? undefined : SOFT}
              onClick={() => setStep(index)}
            >
              {index + 1} · {name}
            </button>
          ))}
        </nav>
      </aside>
      <main className="flex min-w-0 flex-1 flex-col px-12 py-10 max-[1000px]:px-6 max-[1000px]:py-6">
        {step === 0 ? <Agents data={data} /> : step === 1 ? <Roster data={data} /> : <Workspace data={data} />}
        <div className="flex-1" />
        <div className="mt-6 flex items-center justify-between gap-3">
          <span className="text-muted-foreground">
            {step === 0 ? `${connected} connected` : step === 2 && data.workspace ? (
              <button type="button" className="font-mono text-xs hover:underline" onClick={() => send({ type: 'editWorkspaceConfig' })}>
                Saved to .agentdeck/config.toml
              </button>
            ) : step === 1 ? (
              'Saved to your settings'
            ) : null}
          </span>
          <button
            type="button"
            className="h-12 rounded-[10px] bg-primary px-6 text-[15px] font-bold text-primary-foreground"
            onClick={() => (step < 2 ? setStep(step + 1) : send({ type: 'finishSetup' }))}
          >
            {step < 2 ? 'Continue' : 'Finish setup'}
          </button>
        </div>
      </main>
    </div>
  )
}
