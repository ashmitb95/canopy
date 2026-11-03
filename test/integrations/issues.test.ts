import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { createPullRequest, githubIssue, laneName, linearIssue, seedLane } from '../../src/integrations/issues'
import { LaneMemory } from '../../src/lanes/memory'

describe('issues', () => {
  it('reads a GitHub issue through gh, by number or link', async () => {
    const calls: string[][] = []
    const runner = async (_file: string, args: string[]) => {
      calls.push(args)
      return JSON.stringify({ number: 482, title: 'Dark mode loses contrast', url: 'https://github.com/o/r/issues/482', body: 'Tables', comments: [{ author: { login: 'ana' }, body: 'Also lists' }] })
    }
    const issue = await githubIssue('/w', 'https://github.com/o/r/issues/482', runner)
    expect(issue).toMatchObject({ id: '#482', title: 'Dark mode loses contrast', comments: ['ana: Also lists'] })
    expect(calls[0]).toEqual(['issue', 'view', '482', '--json', 'number,title,url,body,comments', '--repo', 'o/r'])
    await expect(githubIssue('/w', 'nope', runner)).rejects.toThrow('Not a GitHub issue')
  })

  it('reads a Linear issue with the key sent only to Linear', async () => {
    let sent: { url: string; auth: string } | undefined
    const fetcher = (async (url: string, init: RequestInit) => {
      sent = { url, auth: String((init.headers as Record<string, string>).authorization) }
      return new Response(JSON.stringify({ data: { issue: { identifier: 'ENG-214', title: 'Exports time out', url: 'https://linear.app/x/issue/ENG-214', description: 'Big invoices', comments: { nodes: [{ body: 'Seen on 50k rows', user: { name: 'Raj' } }] } } } }))
    }) as typeof fetch
    expect(await linearIssue('ENG-214', 'lin_key', fetcher)).toMatchObject({ id: 'ENG-214', comments: ['Raj: Seen on 50k rows'] })
    expect(sent).toEqual({ url: 'https://api.linear.app/graphql', auth: 'lin_key' })
    const missing = (async () => new Response(JSON.stringify({ errors: [{ message: 'Entity not found' }] }))) as unknown as typeof fetch
    await expect(linearIssue('ENG-1', 'k', missing)).rejects.toThrow('Entity not found')
  })

  it('names the lane from the issue, and seeds its goal and notes', () => {
    const issue = { source: 'linear' as const, id: 'ENG-214', title: 'Exports time out on large invoices!', url: 'u', body: 'Big ones', comments: ['Raj: seen'] }
    expect(laneName(issue)).toBe('eng-214-exports-time-out-on-large')
    const memory = new LaneMemory(mkdtempSync(join(tmpdir(), 'agentdeck-issue-')))
    seedLane(memory, 'eng-214', issue)
    expect(memory.goal('eng-214')).toBe('Exports time out on large invoices! (ENG-214)')
    expect(readFileSync(memory.notesPath('eng-214'), 'utf8')).toContain('Big ones')
    expect(readFileSync(memory.notesPath('eng-214'), 'utf8')).toContain('- Raj: seen')
  })

  it('pushes without force, then opens the pull request', async () => {
    const calls: string[] = []
    const runner = async (file: string, args: string[]) => {
      calls.push([file, ...args].join(' '))
      return file === 'gh' ? 'https://github.com/o/r/pull/9\n' : ''
    }
    expect(await createPullRequest('/w', { branch: 'eng-214', base: 'main', title: 'T', body: 'B' }, runner)).toBe('https://github.com/o/r/pull/9')
    expect(calls[0]).toBe('git push --set-upstream origin eng-214')
    expect(calls.join(' ')).not.toContain('--force')
  })
})
