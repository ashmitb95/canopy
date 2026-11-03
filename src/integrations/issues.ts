import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import type { LaneMemory } from '../lanes/memory'
import { laneName } from './lane-name'

export { laneName }

const exec = promisify(execFile)

export type Issue = { source: 'github' | 'linear'; id: string; title: string; url: string; body: string; comments: string[] }

/** Runs a command and returns stdout; replaceable in tests. */
export type Runner = (file: string, args: string[], cwd: string) => Promise<string>
const run: Runner = async (file, args, cwd) => (await exec(file, args, { cwd, maxBuffer: 16 * 1024 * 1024 })).stdout

/** A GitHub issue, through the user's own `gh` login. AgentDeck holds no GitHub token. */
export async function githubIssue(cwd: string, ref: string, runner: Runner = run): Promise<Issue> {
  const number = /(\d+)\s*$/.exec(ref)?.[1]
  if (!number) throw new Error(`Not a GitHub issue: ${ref}`)
  const repo = /github\.com\/([^/]+\/[^/]+)\/issues/.exec(ref)?.[1]
  const args = ['issue', 'view', number, '--json', 'number,title,url,body,comments', ...(repo ? ['--repo', repo] : [])]
  const data = JSON.parse(await runner('gh', args, cwd)) as { number: number; title: string; url: string; body: string; comments: { author?: { login?: string }; body: string }[] }
  return { source: 'github', id: `#${data.number}`, title: data.title, url: data.url, body: data.body ?? '', comments: data.comments.map((comment) => `${comment.author?.login ?? 'someone'}: ${comment.body}`) }
}

/** An issue in a list, before its text is fetched. */
export type IssueRef = Pick<Issue, 'source' | 'id' | 'title' | 'url'>

/** Open GitHub issues for the repo: the user's own first, then the newest. */
export async function githubIssues(cwd: string, runner: Runner = run): Promise<IssueRef[]> {
  const list = async (extra: string[]) =>
    (JSON.parse(await runner('gh', ['issue', 'list', '--state', 'open', ...extra, '--limit', '10', '--json', 'number,title,url'], cwd)) as { number: number; title: string; url: string }[]).map(
      (issue): IssueRef => ({ source: 'github', id: `#${issue.number}`, title: issue.title, url: issue.url })
    )
  const mine = await list(['--assignee', '@me'])
  const newest = await list([])
  return [...mine, ...newest.filter((issue) => !mine.some((own) => own.id === issue.id))].slice(0, 10)
}

/** Open Linear issues assigned to the user. */
export async function linearIssues(apiKey: string, fetcher: typeof fetch = fetch): Promise<IssueRef[]> {
  const query = 'query { viewer { assignedIssues(first: 10, filter: { state: { type: { nin: ["completed", "canceled"] } } }) { nodes { identifier title url } } } }'
  const response = await fetcher('https://api.linear.app/graphql', {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: apiKey },
    body: JSON.stringify({ query })
  })
  if (!response.ok) throw new Error(`Linear answered ${response.status}.`)
  const data = (await response.json()) as { data?: { viewer?: { assignedIssues?: { nodes: { identifier: string; title: string; url: string }[] } } }; errors?: { message: string }[] }
  const nodes = data.data?.viewer?.assignedIssues?.nodes
  if (!nodes) throw new Error(data.errors?.[0]?.message ?? 'Linear sent no issues.')
  return nodes.map((issue) => ({ source: 'linear', id: issue.identifier, title: issue.title, url: issue.url }))
}

/** A Linear issue, with an API key the user added. The key goes only to Linear's API. */
export async function linearIssue(identifier: string, apiKey: string, fetcher: typeof fetch = fetch): Promise<Issue> {
  const query = 'query($id: String!) { issue(id: $id) { identifier title url description comments { nodes { body user { name } } } } }'
  const response = await fetcher('https://api.linear.app/graphql', {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: apiKey },
    body: JSON.stringify({ query, variables: { id: identifier } })
  })
  if (!response.ok) throw new Error(`Linear answered ${response.status}.`)
  const data = (await response.json()) as { data?: { issue?: { identifier: string; title: string; url: string; description?: string; comments?: { nodes: { body: string; user?: { name?: string } }[] } } }; errors?: { message: string }[] }
  const issue = data.data?.issue
  if (!issue) throw new Error(data.errors?.[0]?.message ?? `No Linear issue ${identifier}.`)
  return { source: 'linear', id: issue.identifier, title: issue.title, url: issue.url, body: issue.description ?? '', comments: (issue.comments?.nodes ?? []).map((comment) => `${comment.user?.name ?? 'someone'}: ${comment.body}`) }
}


/** Fetched once by the app, so agents spend no context on it: the lane's goal, and the issue in its notes for every brief to point at. */
export function seedLane(memory: LaneMemory, lane: string, issue: Issue): void {
  memory.ensure(lane)
  memory.setGoal(lane, `${issue.title} (${issue.id})`)
  const comments = issue.comments.length > 0 ? `\n\n### Comments\n\n${issue.comments.map((comment) => `- ${comment.replace(/\n+/g, ' ')}`).join('\n')}` : ''
  memory.appendNote(lane, `## Issue ${issue.id}: ${issue.title}\n\n${issue.url}\n\n${issue.body.trim()}${comments}`)
}

/** Pushes the lane's branch and opens a pull request through the user's `gh` login. Never force-pushes. */
export async function createPullRequest(cwd: string, options: { branch: string; base: string; title: string; body: string }, runner: Runner = run): Promise<string> {
  await runner('git', ['push', '--set-upstream', 'origin', options.branch], cwd)
  const url = await runner('gh', ['pr', 'create', '--head', options.branch, '--base', options.base, '--title', options.title, '--body', options.body], cwd)
  return url.trim().split('\n').at(-1) ?? ''
}
