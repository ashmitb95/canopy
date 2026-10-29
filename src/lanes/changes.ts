import { join } from 'node:path'
import { git } from './git'

export type FileChange = { path: string; status: 'added' | 'modified' | 'deleted'; ref: string }

/** Everything a checkout changed since it left `base`: commits, uncommitted edits, and untracked files. `ref` is the merge base. */
export async function checkoutChanges(checkout: string, base: string): Promise<FileChange[]> {
  const ref = (await git(checkout, ['merge-base', base, 'HEAD'])).trim()
  const fields = (await git(checkout, ['diff', '--name-status', '--no-renames', '-z', ref])).split('\0').filter(Boolean)
  const changes: FileChange[] = []
  for (let index = 0; index + 1 < fields.length; index += 2) {
    const letter = fields[index]
    changes.push({
      path: join(checkout, fields[index + 1]),
      status: letter === 'A' ? 'added' : letter === 'D' ? 'deleted' : 'modified',
      ref
    })
  }
  const untracked = (await git(checkout, ['ls-files', '--others', '--exclude-standard', '-z'])).split('\0').filter(Boolean)
  for (const file of untracked) changes.push({ path: join(checkout, file), status: 'added', ref })
  return changes
}
