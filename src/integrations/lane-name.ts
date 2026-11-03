// No Node or VS Code imports: the New Worktree form uses this too.

/** A branch name from an issue: `eng-214-export-timeouts`. */
export function laneName(issue: { id: string; title: string }): string {
  const slug = issue.title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .split('-')
    .slice(0, 5)
    .join('-')
  return `${issue.id.replace('#', '').toLowerCase()}-${slug}`.replace(/-+$/, '')
}
