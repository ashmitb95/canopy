import { describe, expect, it } from 'vitest'
import { rankFiles } from '../../src/ui/rank-files'

const files = ['src/api/retry.ts', 'src/api.test.ts', 'docs/retry-notes.md', 'src/server/router.ts', 'README.md']

describe('rankFiles', () => {
  it('ranks name prefixes, then name matches, then path matches, then subsequences', () => {
    expect(rankFiles(files, 'retry', new Set())).toEqual(['src/api/retry.ts', 'docs/retry-notes.md'])
    expect(rankFiles(files, 'api', new Set())).toEqual(['src/api.test.ts', 'src/api/retry.ts'])
    expect(rankFiles(files, 'srvr', new Set())).toEqual(['src/server/router.ts'])
  })

  it('puts recently opened files first and lists everything for an empty query', () => {
    expect(rankFiles(files, '', new Set(['README.md']))[0]).toBe('README.md')
    expect(rankFiles(files, '', new Set())).toHaveLength(files.length)
  })

  it('limits the list', () => {
    expect(rankFiles(files, '', new Set(), 2)).toHaveLength(2)
  })
})
