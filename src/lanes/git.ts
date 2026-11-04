import { execFile } from 'node:child_process'

/** A git command that failed. `args` is what was run, so a buffer error names the command instead of only saying the buffer filled up. */
export class GitError extends Error {
  constructor(
    message: string,
    readonly cwd: string,
    readonly args: string[]
  ) {
    super(message)
  }
}

/** One line for the output channel: the message, and the command when git produced it. */
export function formatFailure(error: unknown): string {
  if (error instanceof GitError) return `${error.message} — ${error.cwd}: git ${error.args.join(' ')}`
  if (error instanceof Error) return error.message
  return String(error)
}

/** Runs git and returns stdout. Optional locks are off so reading status never rewrites the index, which the watcher would see. */
export function git(cwd: string, args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(
      'git',
      args,
      { cwd, env: { ...process.env, GIT_OPTIONAL_LOCKS: '0' }, maxBuffer: 16 * 1024 * 1024 },
      (error, stdout, stderr) => (error ? reject(new GitError(stderr.trim() || error.message, cwd, args)) : resolve(stdout))
    )
  })
}
