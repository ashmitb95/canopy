// Live check: "done" is honoured only when work has really stopped, and the lead acts on what actually happened.
import { existsSync, readFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { captureEnv, type Env } from '../src/env'
import { Group, tempRepo } from './group'
import { activity, baseline, type Outcome, stop, waitForSettled } from './settle'

const line = (name: string, ok: boolean | string, detail = '') => console.log(`${ok === true ? 'PASS' : ok === false ? 'FAIL' : String(ok)}  ${name}${detail ? `  ${detail.replace(/\s+/g, ' ').slice(0, 230)}` : ''}`)
const describeWork = (outcome: Outcome) => [...outcome.activity.work.map((proc) => proc.command), ...outcome.activity.services.map((proc) => `${proc.command} (port ${proc.ports.join(',')})`)].map((text) => text.slice(0, 70)).join('; ')

async function setup(env: Env, worker: string, lead: string, stopped: number[] = []) {
  const repo = tempRepo()
  const group = new Group(repo, env, { lead, implement: worker }, worker, [
    {
      name: 'stop_work',
      description: 'Stops a process a delegate left running, by pid.',
      inputSchema: { type: 'object', properties: { pid: { type: 'number' } }, required: ['pid'] },
      call: (args) => {
        stopped.push(Number(args.pid))
        stop([Number(args.pid)])
        return 'Stopped. End your turn now.'
      }
    }
  ])
  const workerSession = await group.ready(worker)
  await group.ready(lead)
  await new Promise((resolve) => setTimeout(resolve, 3_000))
  const base = await baseline(repo)
  return { repo, group, base, workerSession }
}

const finishUp = async (repo: string, group: Group, base: Set<number>) => {
  const left = await activity(repo, base)
  stop([...left.work, ...left.services].map((proc) => proc.pid))
  await group.close()
  rmSync(repo, { recursive: true, force: true })
}

/** A plain turn must not look busy: no false positives from the CLI or its helpers. */
async function quiet(env: Env, worker: string, lead: string): Promise<void> {
  const { repo, group, base } = await setup(env, worker, lead)
  try {
    await group.turn(worker, 'Run this shell command and wait for it: echo hello. Then end with STATUS: done.')
    const outcome = await waitForSettled(repo, base, 15_000)
    line(`${worker} plain turn: settled, no false positive`, outcome.settled && outcome.waitedMs < 8_000, `${outcome.waitedMs}ms ${describeWork(outcome)}`)
  } catch (error) {
    line(`${worker} plain turn`, false, (error as Error).message)
  } finally {
    await finishUp(repo, group, base)
  }
}

/** The delegate reports done early; only the real finish wakes the lead, and a failure cannot slip through. */
async function early(env: Env, worker: string, lead: string): Promise<void> {
  const { repo, group, base, workerSession } = await setup(env, worker, lead)
  const name = `${worker} reports early`
  try {
    let woke = 0
    const started = Date.now()
    const off = workerSession.onItem((item) => {
      if (item.kind === 'turn' && item.state === 'started' && Date.now() - started > 1_000) woke += 1
    })
    const run = await group.turn(worker, 'Start this in the background and do not wait for it: (sleep 25; echo FAILED > result.log) &   Then end your turn immediately with the line STATUS: done.')
    const atReport = await activity(repo, base)
    line(`${name}: work still running when it said done`, atReport.work.length > 0 && !existsSync(join(repo, 'result.log')), `${/STATUS:.*/.exec(run.reply)?.[0] ?? 'no status'} | ${atReport.work.map((proc) => proc.command.slice(0, 50)).join('; ')}`)
    const outcome = await waitForSettled(repo, base, 90_000)
    off.dispose()
    line(`${name}: settled only when it really finished`, outcome.settled && existsSync(join(repo, 'result.log')), `waited ${Math.round(outcome.waitedMs / 1000)}s, ${existsSync(join(repo, 'result.log')) ? readFileSync(join(repo, 'result.log'), 'utf8').trim() : 'no result'}`)
    console.log(`INFO  ${name}: CLI woke itself ${woke} time(s) while waiting`)
    const check = await group.turn(worker, 'Your background work has now really finished. Read result.log and correct your report. End with STATUS: done only if it succeeded; otherwise STATUS: blocked and say why.')
    line(`${name}: delegate corrected its report`, /STATUS:\s*blocked/i.test(check.reply) || /fail/i.test(check.reply), /STATUS:.*/.exec(check.reply)?.[0] ?? check.reply)
    const leadRun = await group.turn(lead, `You lead this chat and own your delegates. ${worker} reported done early, but AgentDeck held that until its background work really ended. Report now:\n${check.reply}\nSay in one sentence whether the task succeeded and what you would do next.`)
    line(`${name}: lead acts on the real result`, /fail/i.test(leadRun.reply) && !/succeeded\b(?!.*not)/i.test(leadRun.reply.replace(/did not succeed/gi, '')), leadRun.reply)
  } catch (error) {
    line(name, false, (error as Error).message)
  } finally {
    await finishUp(repo, group, base)
  }
}

/** A server never finishes: not waited for, and the lead can stop it. */
async function service(env: Env, worker: string, lead: string): Promise<void> {
  const stopped: number[] = []
  const { repo, group, base } = await setup(env, worker, lead, stopped)
  const name = `${worker} leaves a server`
  try {
    await group.turn(worker, `Start this in the background and do not wait for it: node -e 'require("http").createServer(()=>{}).listen(0)' &   Then end your turn with STATUS: done.`)
    await new Promise((resolve) => setTimeout(resolve, 1_500))
    const outcome = await waitForSettled(repo, base, 20_000)
    const server = outcome.activity.services[0]
    line(`${name}: not waited for, recorded as a service`, outcome.settled && Boolean(server), describeWork(outcome))
    if (!server) return
    await group.turn(lead, `You lead this chat and own your delegates. ${worker} is done and left a process running: pid ${server.pid}, listening on port ${server.ports[0]}. Nothing needs it any more, so stop it with stop_work.`)
    await new Promise((resolve) => setTimeout(resolve, 1_000))
    const after = await activity(repo, base)
    line(`${name}: lead stopped it`, stopped.includes(server.pid) && after.services.length === 0, `lead called stop_work on ${stopped.join(',') || 'nothing'}`)
  } catch (error) {
    line(name, false, (error as Error).message)
  } finally {
    await finishUp(repo, group, base)
  }
}

/** Past the limit, AgentDeck tells the lead, and the lead decides. */
async function overdue(env: Env, worker: string, lead: string): Promise<void> {
  const stopped: number[] = []
  const { repo, group, base } = await setup(env, worker, lead, stopped)
  const name = `${worker} overruns`
  try {
    await group.turn(worker, 'Start this in the background and do not wait for it: sleep 300 &   Then end your turn with STATUS: done.')
    const outcome = await waitForSettled(repo, base, 12_000)
    line(`${name}: reported past the limit, no hang`, !outcome.settled, describeWork(outcome))
    const pids = outcome.activity.work.map((proc) => `${proc.pid} (${proc.command.slice(0, 40)})`).join(', ')
    await group.turn(lead, `You lead this chat and own your delegates. ${worker} reported done, but this is still running after 12 seconds: ${pids}. The task did not need a five-minute wait. Decide: stop it with stop_work, or say you will keep waiting.`)
    const after = await waitForSettled(repo, base, 5_000)
    line(`${name}: lead decided, and the work stopped`, stopped.length > 0 && after.settled, `stopped ${stopped.join(',') || 'nothing'}`)
  } catch (error) {
    line(name, false, (error as Error).message)
  } finally {
    await finishUp(repo, group, base)
  }
}

async function main(): Promise<void> {
  const env = await captureEnv()
  for (const [worker, lead] of [['claude', 'codex'], ['codex', 'claude'], ['grok', 'claude']]) {
    await quiet(env, worker, lead)
    await early(env, worker, lead)
    await service(env, worker, lead)
    await overdue(env, worker, lead)
  }
  console.log('DONE')
  process.exit(0)
}

void main()
