import { describe, expect, it } from 'vitest'
import { claudeWritePaths, switchesBranch, writable } from '../../src/providers/boundary'

const boundary = { roots: ['/w/api', '/w/.canopy/lanes/x'], except: ['/w/api/.worktrees/other'], outside: async () => '' }

describe('boundary', () => {
  it('allows writes under roots but not into other lanes nested inside them', () => {
    expect(writable(boundary, '/w/api/src/a.ts')).toBe(true)
    expect(writable(boundary, '/w/api')).toBe(true)
    expect(writable(boundary, '/w/.canopy/lanes/x/plan.md')).toBe(true)
    expect(writable(boundary, '/w/api/.worktrees/other/a.ts')).toBe(false)
    expect(writable(boundary, '/w/api-old/a.ts')).toBe(false)
    expect(writable(boundary, '/w/ui/a.ts')).toBe(false)
  })

  it('finds the paths Claude tools write, relative to the cwd', () => {
    expect(claudeWritePaths('Edit', { file_path: 'api/a.ts' }, '/w')).toEqual(['/w/api/a.ts'])
    expect(claudeWritePaths('Write', { file_path: '/w/b.ts' }, '/w')).toEqual(['/w/b.ts'])
    expect(claudeWritePaths('NotebookEdit', { notebook_path: '/w/n.ipynb' }, '/w')).toEqual(['/w/n.ipynb'])
    expect(claudeWritePaths('Read', { file_path: '/w/c.ts' }, '/w')).toEqual([])
  })

  it('spots branch switches but not file restores', () => {
    expect(switchesBranch('git checkout main')).toBe(true)
    expect(switchesBranch('cd api && git switch -c x')).toBe(true)
    expect(switchesBranch('git -C api checkout feat')).toBe(true)
    expect(switchesBranch('git checkout -- src/a.ts')).toBe(false)
    expect(switchesBranch('git status')).toBe(false)
  })
})
