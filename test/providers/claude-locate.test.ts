import { chmodSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { findClaude } from '../../src/providers/claude/locate'

function fakeCli(path: string, version: string): string {
  mkdirSync(join(path, '..'), { recursive: true })
  writeFileSync(path, `#!/bin/sh\necho "${version} (Claude Code)"\n`)
  chmodSync(path, 0o755)
  return path
}

function extensionCli(home: string, version: string): string {
  return fakeCli(join(home, '.vscode', 'extensions', `anthropic.claude-code-${version}-darwin-arm64`, 'resources', 'native-binary', 'claude'), version)
}

describe.skipIf(process.platform === 'win32')('findClaude', () => {
  it('uses the official extension when its CLI is newer than the one on PATH', async () => {
    const root = mkdtempSync(join(tmpdir(), 'canopy-claude-'))
    fakeCli(join(root, 'bin', 'claude'), '2.1.111')
    extensionCli(join(root, 'home'), '2.1.289')
    const newest = extensionCli(join(root, 'home'), '2.1.311')
    await expect(findClaude({ PATH: join(root, 'bin') }, join(root, 'home'))).resolves.toBe(newest)
  })

  it('keeps the CLI on PATH when it is the newest', async () => {
    const root = mkdtempSync(join(tmpdir(), 'canopy-claude-'))
    const onPath = fakeCli(join(root, 'bin', 'claude'), '2.2.0')
    extensionCli(join(root, 'home'), '2.1.311')
    await expect(findClaude({ PATH: join(root, 'bin') }, join(root, 'home'))).resolves.toBe(onPath)
  })

  it('falls back to the extension when claude is not on PATH, and to null when absent', async () => {
    const root = mkdtempSync(join(tmpdir(), 'canopy-claude-'))
    const bundled = extensionCli(join(root, 'home'), '2.1.311')
    await expect(findClaude({ PATH: '' }, join(root, 'home'))).resolves.toBe(bundled)
    await expect(findClaude({ PATH: '' }, join(root, 'empty'))).resolves.toBeNull()
  })
})
