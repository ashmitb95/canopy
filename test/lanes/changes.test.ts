import { rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { checkoutChanges } from '../../src/lanes/changes'
import { repo, run, workspace } from './repos'

describe('checkoutChanges', () => {
  it('lists commits since base, uncommitted edits, and untracked files', async () => {
    const api = repo(join(workspace(), 'api'))
    writeFileSync(join(api, 'gone.txt'), 'x')
    run(api, 'add', '.')
    run(api, 'commit', '-q', '-m', 'gone')
    run(api, 'checkout', '-q', '-b', 'lane')
    writeFileSync(join(api, 'README.md'), 'changed')
    rmSync(join(api, 'gone.txt'))
    run(api, 'commit', '-q', '-am', 'work')
    writeFileSync(join(api, 'committed-later.txt'), 'y')
    run(api, 'add', '.')
    run(api, 'commit', '-q', '-m', 'add')
    writeFileSync(join(api, 'README.md'), 'changed again')
    writeFileSync(join(api, 'new.txt'), 'n')
    const changes = await checkoutChanges(api, 'main')
    const base = run(api, 'rev-parse', 'main').trim()
    expect(changes.sort((a, b) => (a.path < b.path ? -1 : 1))).toEqual([
      { path: join(api, 'README.md'), status: 'modified', ref: base },
      { path: join(api, 'committed-later.txt'), status: 'added', ref: base },
      { path: join(api, 'gone.txt'), status: 'deleted', ref: base },
      { path: join(api, 'new.txt'), status: 'added', ref: base }
    ])
  })
})
