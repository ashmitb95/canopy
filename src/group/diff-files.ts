export type DiffFile = { path: string; added: number; removed: number; lines: string[] }

/** A `git diff` split per file, with its hunks and line counts. */
export function diffFiles(diff: string): DiffFile[] {
  const files: DiffFile[] = []
  let current: DiffFile | undefined
  let inHunk = false
  for (const line of diff.split('\n')) {
    const header = /^diff --git a\/(.+) b\/(.+)$/.exec(line)
    if (header) {
      current = { path: header[2], added: 0, removed: 0, lines: [] }
      files.push(current)
      inHunk = false
      continue
    }
    if (!current) continue
    if (line.startsWith('@@')) inHunk = true
    if (!inHunk) continue
    current.lines.push(line)
    if (line.startsWith('+')) current.added++
    else if (line.startsWith('-')) current.removed++
  }
  for (const file of files) if (file.lines.at(-1) === '') file.lines.pop()
  return files
}
