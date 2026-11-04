import { chmodSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { delimiter, join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { captureEnv, findOnPath } from '../src/env'

describe('findOnPath', () => {
  it('finds a command in a later PATH entry', () => {
    const dir = mkdtempSync(join(tmpdir(), 'canopy-env-'))
    const cli = join(dir, 'fake-cli')
    writeFileSync(cli, '#!/bin/sh\n')
    chmodSync(cli, 0o755)
    expect(findOnPath({ PATH: `${join(dir, 'missing')}${delimiter}${dir}` }, 'fake-cli')).toBe(cli)
  })

  it('returns null when the command is absent', () => {
    expect(findOnPath({ PATH: tmpdir() }, 'canopy-no-such-cli')).toBeNull()
  })
})

describe('captureEnv', () => {
  it('copies the base environment, dropping undefined values', async () => {
    const env = await captureEnv({ PATH: '/bin', FOO: '1', EMPTY: undefined })
    expect(env).toEqual({ PATH: '/bin', FOO: '1' })
  })
})
