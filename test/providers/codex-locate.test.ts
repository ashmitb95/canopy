import { chmodSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { findCodex } from '../../src/providers/codex/locate'

function executable(path: string): string {
  mkdirSync(join(path, '..'), { recursive: true })
  writeFileSync(path, '#!/bin/sh\n')
  chmodSync(path, 0o755)
  return path
}

describe('findCodex', () => {
  it('prefers codex on PATH', () => {
    const dir = mkdtempSync(join(tmpdir(), 'canopy-codex-'))
    const cli = executable(join(dir, 'bin', 'codex'))
    expect(findCodex({ PATH: join(dir, 'bin') }, join(dir, 'home'))).toBe(cli)
  })

  it('falls back to the newest official Codex extension', () => {
    const home = mkdtempSync(join(tmpdir(), 'canopy-home-'))
    const extensions = join(home, '.vscode', 'extensions')
    executable(join(extensions, 'openai.chatgpt-26.930.41038-darwin-arm64', 'bin', 'macos-aarch64', 'codex'))
    const newest = executable(join(extensions, 'openai.chatgpt-26.1021.22027-darwin-arm64', 'bin', 'macos-aarch64', 'codex'))
    executable(join(extensions, 'openai.chatgpt-26.1007.21434-darwin-arm64', 'bin', 'macos-aarch64', 'codex'))
    expect(findCodex({ PATH: '' }, home)).toBe(newest)
  })

  it('returns null when Codex is nowhere', () => {
    expect(findCodex({ PATH: '' }, mkdtempSync(join(tmpdir(), 'canopy-empty-')))).toBeNull()
  })
})
