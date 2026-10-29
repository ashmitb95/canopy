import { type Dirent, existsSync } from 'node:fs'
import { readdir } from 'node:fs/promises'
import { join } from 'node:path'

const SKIP = new Set(['node_modules', 'dist', 'build', 'out', 'target', 'vendor'])

/** Git repositories at or under the root. A repo's own folders, hidden folders, and dependency folders are not searched. */
export async function discoverRepos(root: string, depth = 3): Promise<string[]> {
  if (existsSync(join(root, '.git'))) return [root]
  const found: string[] = []
  const walk = async (dir: string, left: number): Promise<void> => {
    if (left === 0) return
    let entries: Dirent[]
    try {
      entries = await readdir(dir, { withFileTypes: true })
    } catch {
      return
    }
    for (const entry of entries) {
      if (!entry.isDirectory() || entry.name.startsWith('.') || SKIP.has(entry.name)) continue
      const path = join(dir, entry.name)
      if (existsSync(join(path, '.git'))) found.push(path)
      else await walk(path, left - 1)
    }
  }
  await walk(root, depth)
  return found.sort()
}
