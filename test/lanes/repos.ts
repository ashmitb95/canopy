import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, realpathSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export function run(cwd: string, ...args: string[]): string {
  return execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
}

/** A temporary workspace root (real path: macOS tmpdir is behind a symlink, and git prints real paths). */
export function workspace(): string {
  return realpathSync(mkdtempSync(join(tmpdir(), 'canopy-lanes-')))
}

/** A repo with one commit on `main`. */
export function repo(path: string): string {
  mkdirSync(path, { recursive: true })
  run(path, 'init', '-q', '-b', 'main')
  run(path, 'config', 'user.email', 'test@example.com')
  run(path, 'config', 'user.name', 'Test')
  run(path, 'config', 'commit.gpgsign', 'false')
  writeFileSync(join(path, 'README.md'), '# repo\n')
  run(path, 'add', '.')
  run(path, 'commit', '-q', '-m', 'init')
  return path
}
