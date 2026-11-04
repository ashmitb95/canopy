import { describe, expect, it } from 'vitest'
import { join } from 'node:path'
import { GitError, formatFailure, git } from '../../src/lanes/git'
import { repo, workspace } from './repos'

describe('git failures', () => {
  it('attaches the command to a failed git call', async () => {
    const root = repo(join(workspace(), 'api'))
    const error = await git(root, ['rev-parse', 'no-such-ref']).then(
      () => undefined,
      (caught: unknown) => caught
    )
    expect(error).toBeInstanceOf(GitError)
    expect(error).toMatchObject({ cwd: root, args: ['rev-parse', 'no-such-ref'] })
  })

  it('includes the git command when describing a failure', () => {
    const error = new GitError('stdout maxBuffer length exceeded', '/repo', ['ls-files', '--others', '--ignored', '--exclude-standard'])
    expect(formatFailure(error)).toBe('stdout maxBuffer length exceeded — /repo: git ls-files --others --ignored --exclude-standard')
  })
})
