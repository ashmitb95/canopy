import { appendFileSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { parseToml, stringifyToml } from './toml'

export type ChatSummaryRef = { chatId: string; title: string; path: string; updated: string }

/** `.agentdeck/` at the workspace root: what each lane is for and what its chats found. It never describes Git. */
export class LaneMemory {
  readonly dir: string

  constructor(private readonly root: string) {
    this.dir = join(root, '.agentdeck')
  }

  laneDir(lane: string): string {
    return join(this.dir, 'lanes', lane.replaceAll('/', '--'))
  }

  planPath(lane: string): string {
    return join(this.laneDir(lane), 'plan.md')
  }

  notesPath(lane: string): string {
    return join(this.laneDir(lane), 'notes.md')
  }

  exists(lane: string): boolean {
    return existsSync(this.laneDir(lane))
  }

  ensure(lane: string): void {
    const dir = this.laneDir(lane)
    mkdirSync(join(dir, 'chats'), { recursive: true })
    const toml = join(dir, 'lane.toml')
    if (!existsSync(toml)) writeFileSync(toml, stringifyToml({ name: lane, created: new Date().toISOString() }))
    for (const file of [this.planPath(lane), this.notesPath(lane)]) if (!existsSync(file)) writeFileSync(file, '')
    this.exclude()
  }

  goal(lane: string): string | undefined {
    const goal = this.lane(lane).goal
    return typeof goal === 'string' && goal.trim() ? goal.trim() : undefined
  }

  setGoal(lane: string, goal: string): void {
    this.ensure(lane)
    writeFileSync(join(this.laneDir(lane), 'lane.toml'), stringifyToml({ ...this.lane(lane), goal }))
  }

  /** The lane's own worktree toggle; undefined means the workspace default. */
  worktrees(lane: string): boolean | undefined {
    const value = this.lane(lane).worktrees
    return typeof value === 'boolean' ? value : undefined
  }

  setWorktrees(lane: string, on: boolean): void {
    this.ensure(lane)
    writeFileSync(join(this.laneDir(lane), 'lane.toml'), stringifyToml({ ...this.lane(lane), worktrees: on }))
  }

  /** When plan.md last changed, or undefined while it is empty. */
  planUpdated(lane: string): string | undefined {
    const path = this.planPath(lane)
    if (!existsSync(path)) return undefined
    const stats = statSync(path)
    return stats.size > 0 ? stats.mtime.toISOString() : undefined
  }

  noteCount(lane: string): number {
    const path = this.notesPath(lane)
    if (!existsSync(path)) return 0
    return readFileSync(path, 'utf8')
      .split('\n')
      .filter((line) => line.startsWith('- ')).length
  }

  /** Chat summaries, newest first. */
  summaries(lane: string): ChatSummaryRef[] {
    const dir = join(this.laneDir(lane), 'chats')
    if (!existsSync(dir)) return []
    return readdirSync(dir)
      .filter((file) => file.endsWith('.md'))
      .map((file) => {
        const path = join(dir, file)
        const heading = readFileSync(path, 'utf8')
          .split('\n')
          .find((line) => line.startsWith('# '))
        return {
          chatId: file.slice(0, -'.md'.length),
          title: heading?.slice(2).trim() ?? file,
          path,
          updated: statSync(path).mtime.toISOString()
        }
      })
      .sort((a, b) => b.updated.localeCompare(a.updated))
  }

  writeSummary(lane: string, chatId: string, text: string): void {
    this.ensure(lane)
    writeFileSync(join(this.laneDir(lane), 'chats', `${chatId}.md`), text)
  }

  /** Records an observed event; lanes AgentDeck holds no memory for are not given a folder just for this. */
  appendHistory(lane: string, event: Record<string, unknown>): void {
    if (!this.exists(lane)) return
    appendFileSync(join(this.laneDir(lane), 'history.jsonl'), `${JSON.stringify({ at: new Date().toISOString(), ...event })}\n`)
  }

  private lane(lane: string): Record<string, unknown> {
    const path = join(this.laneDir(lane), 'lane.toml')
    return existsSync(path) ? parseToml(readFileSync(path, 'utf8')) : {}
  }

  /** In a single-repo workspace the root is the repo, so `.agentdeck/` is excluded locally (never in a committed .gitignore). */
  private exclude(): void {
    const gitDir = join(this.root, '.git')
    if (!existsSync(gitDir) || !statSync(gitDir).isDirectory()) return
    const file = join(gitDir, 'info', 'exclude')
    const current = existsSync(file) ? readFileSync(file, 'utf8') : ''
    if (current.split('\n').includes('.agentdeck/')) return
    mkdirSync(join(gitDir, 'info'), { recursive: true })
    appendFileSync(file, `${current && !current.endsWith('\n') ? '\n' : ''}.agentdeck/\n`)
  }
}

/** `<!-- when · by · repo@commit … -->`, so a reader can tell how far each repo moved since. */
export function stamp(by: string, heads: { repo: string; head?: string }[], at = new Date()): string {
  const commits = heads.flatMap(({ repo, head }) => (head ? [`${repo}@${head.slice(0, 7)}`] : []))
  return `<!-- ${[at.toISOString(), by, ...(commits.length > 0 ? [commits.join(' ')] : [])].join(' · ')} -->`
}
