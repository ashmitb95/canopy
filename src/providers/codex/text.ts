const SHELL_WRAPPER = /^\S*\b(?:ba|z)?sh -lc (["'])([\s\S]*)\1$/

/** Codex runs commands as `/bin/zsh -lc "<command>"`; show the command itself. */
export function unwrapShell(command: string): string {
  return command.match(SHELL_WRAPPER)?.[2] ?? command
}

/** The removed and added lines of a unified diff; a diff without hunks is all new content. */
export function splitDiff(diff: string): { oldText: string; newText: string } {
  const lines = diff.split('\n')
  if (!lines.some((line) => line.startsWith('@@'))) return { oldText: '', newText: diff }
  const removed: string[] = []
  const added: string[] = []
  for (const line of lines) {
    if (line.startsWith('---') || line.startsWith('+++')) continue
    if (line.startsWith('-')) removed.push(line.slice(1))
    else if (line.startsWith('+')) added.push(line.slice(1))
  }
  return { oldText: removed.join('\n'), newText: added.join('\n') }
}
