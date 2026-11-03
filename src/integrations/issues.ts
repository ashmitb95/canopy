import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import type { LaneMemory } from '../lanes/memory'

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

/** A branch name from an issue: `eng-214-export-timeouts`. */
export function laneName(issue: Issue): string {
  const slug = issue.title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .split('-')
    .slice(0, 5)
    .join('-')
  return `${issue.id.replace('#', '').toLowerCase()}-${slug}`.replace(/-+$/, '')
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
