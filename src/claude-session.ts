import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { promisify } from 'node:util'
import type { PermissionResult, Query, SDKMessage, SDKUserMessage } from '@anthropic-ai/claude-agent-sdk'

const run = promisify(execFile)

/** What the chat UI renders. Ids are stable so streamed text can be appended in place. */
export type ChatEvent =
  | { type: 'init'; model: string; sessionId: string; apiKeySource: string }
  | { type: 'text'; id: string; delta: string }
  | { type: 'tool'; id: string; name: string; input: unknown }
  | { type: 'tool_result'; id: string; isError: boolean; text: string }
  | { type: 'permission'; id: string; toolName: string; input: unknown }
  | { type: 'turn_end'; durationMs: number; isError: boolean }
  | { type: 'error'; message: string }

export type ClaudeCli = { path: string; env: Record<string, string> }

export type AuthStatus = { loggedIn: boolean; authMethod?: string; email?: string }

/** GUI-launched VS Code lacks the shell's PATH, so read it from a login shell. */
export async function resolveClaudeCli(): Promise<ClaudeCli | null> {
  const env: Record<string, string> = {}
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined) env[key] = value
  }
  const shell = process.env.SHELL
  if (shell && process.platform !== 'win32') {
    try {
      const { stdout } = await run(shell, ['-ilc', 'printf "%s" "$PATH"'], { timeout: 10_000 })
      if (stdout.trim()) env.PATH = stdout.trim()
    } catch {
      // Fall back to the extension host's PATH.
    }
  }
  // An inherited API key would bill the API instead of the claude.ai subscription.
  delete env.ANTHROPIC_API_KEY
  const name = process.platform === 'win32' ? 'claude.exe' : 'claude'
  for (const dir of (env.PATH ?? '').split(delimiter)) {
    const candidate = join(dir, name)
    if (dir && existsSync(candidate)) return { path: candidate, env }
  }
  return null
}

export async function claudeAuthStatus(cli: ClaudeCli): Promise<AuthStatus> {
  try {
    const { stdout } = await run(cli.path, ['auth', 'status'], { env: cli.env, timeout: 15_000 })
    return JSON.parse(stdout) as AuthStatus
  } catch {
    return { loggedIn: false }
  }
}

/** One long-lived claude process per chat; user messages are pushed into its input stream. */
export class ClaudeChat {
  private query: Query | null = null
  private readonly inbox: SDKUserMessage[] = []
  private wake: (() => void) | null = null
  private closed = false
  private readonly pendingPermissions = new Map<
    string,
    { input: Record<string, unknown>; resolve: (result: PermissionResult) => void }
  >()
  private permissionSeq = 0

  constructor(
    private readonly cli: ClaudeCli,
    private readonly cwd: string,
    private readonly emit: (event: ChatEvent) => void
  ) {}

  send(text: string): void {
    this.inbox.push({
      type: 'user',
      message: { role: 'user', content: text },
      parent_tool_use_id: null
    })
    this.wake?.()
    if (!this.query) void this.start()
  }

  respondToPermission(id: string, allow: boolean): void {
    const pending = this.pendingPermissions.get(id)
    if (!pending) return
    this.pendingPermissions.delete(id)
    // The CLI rejects an allow without updatedInput, although the SDK types mark it optional.
    pending.resolve(
      allow
        ? { behavior: 'allow', updatedInput: pending.input }
        : { behavior: 'deny', message: 'The user denied this action.' }
    )
  }

  async interrupt(): Promise<void> {
    await this.query?.interrupt()
  }

  close(): void {
    this.closed = true
    this.wake?.()
    for (const id of [...this.pendingPermissions.keys()]) this.respondToPermission(id, false)
    this.query?.close()
  }

  private async *messages(): AsyncGenerator<SDKUserMessage> {
    while (!this.closed) {
      const next = this.inbox.shift()
      if (next) {
        yield next
        continue
      }
      await new Promise<void>((resolve) => (this.wake = resolve))
      this.wake = null
    }
  }

  private async start(): Promise<void> {
    // Loaded on first prompt so opening a chat stays fast.
    const { query } = await import('@anthropic-ai/claude-agent-sdk')
    this.query = query({
      prompt: this.messages(),
      options: {
        pathToClaudeCodeExecutable: this.cli.path,
        cwd: this.cwd,
        env: this.cli.env,
        includePartialMessages: true,
        systemPrompt: { type: 'preset', preset: 'claude_code' },
        settingSources: ['user', 'project', 'local'],
        permissionMode: 'default',
        canUseTool: (toolName, input, { signal }) =>
          new Promise<PermissionResult>((resolve) => {
            const id = `perm-${++this.permissionSeq}`
            this.pendingPermissions.set(id, { input, resolve })
            signal.addEventListener('abort', () => this.respondToPermission(id, false))
            this.emit({ type: 'permission', id, toolName, input })
          })
      }
    })
    try {
      for await (const message of this.query) this.translate(message)
    } catch (error) {
      if (!this.closed) this.emit({ type: 'error', message: error instanceof Error ? error.message : String(error) })
    }
  }

  private currentMessageId = ''
  private sessionId = ''

  private translate(message: SDKMessage): void {
    switch (message.type) {
      case 'system':
        // The CLI re-sends init every turn; surface it once per session.
        if (message.subtype === 'init' && message.session_id !== this.sessionId) {
          this.sessionId = message.session_id
          this.emit({
            type: 'init',
            model: message.model,
            sessionId: message.session_id,
            apiKeySource: message.apiKeySource
          })
        }
        return
      case 'stream_event': {
        // Subagent output is left out of the POC transcript.
        if (message.parent_tool_use_id) return
        const event = message.event
        if (event.type === 'message_start') this.currentMessageId = event.message.id
        if (event.type === 'content_block_delta' && event.delta.type === 'text_delta') {
          this.emit({ type: 'text', id: `${this.currentMessageId}:${event.index}`, delta: event.delta.text })
        }
        return
      }
      case 'assistant':
        if (message.parent_tool_use_id) return
        for (const block of message.message.content) {
          if (block.type === 'tool_use') this.emit({ type: 'tool', id: block.id, name: block.name, input: block.input })
        }
        return
      case 'user': {
        if (message.parent_tool_use_id || typeof message.message.content === 'string') return
        for (const block of message.message.content) {
          if (block.type !== 'tool_result') continue
          const text =
            typeof block.content === 'string'
              ? block.content
              : (block.content ?? []).map((part) => (part.type === 'text' ? part.text : `[${part.type}]`)).join('\n')
          this.emit({ type: 'tool_result', id: block.tool_use_id, isError: block.is_error === true, text })
        }
        return
      }
      case 'result':
        this.emit({ type: 'turn_end', durationMs: message.duration_ms, isError: message.is_error })
        return
    }
  }
}
