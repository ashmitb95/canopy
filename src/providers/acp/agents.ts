import { existsSync } from 'node:fs'
import { join } from 'node:path'
import type { AcpAgentSpec } from './spec'

export const grok: AcpAgentSpec = {
  id: 'grok',
  label: 'Grok',
  command: 'grok',
  installUrl: 'https://x.ai/cli',
  args: ['agent', 'stdio'],
  loginArgs: ['login'],
  installDirs: (home) => [join(home, '.grok', 'bin')],
  authMethod: (advertised, env) =>
    env.XAI_API_KEY?.trim() && advertised.includes('xai.api_key')
      ? 'xai.api_key'
      : advertised.includes('cached_token')
        ? 'cached_token'
        : undefined,
  signedIn: (env, home) => Boolean(env.XAI_API_KEY?.trim()) || existsSync(join(home, '.grok', 'auth.json'))
}

export const cursor: AcpAgentSpec = {
  id: 'cursor',
  label: 'Cursor',
  // Cursor's docs name the binary `agent`; Grok's CLI installs another `agent`, so use Cursor's `cursor-agent`.
  command: 'cursor-agent',
  installUrl: 'https://cursor.com/docs/cli/installation',
  args: ['acp'],
  loginArgs: ['login'],
  installDirs: (home) => [join(home, '.local', 'bin')],
  authMethod: () => undefined,
  // Cursor keeps its login in its own store; without an API key, a missing login surfaces as the agent's own error.
  signedIn: () => true
}

export const opencode: AcpAgentSpec = {
  id: 'opencode',
  label: 'OpenCode',
  command: 'opencode',
  installUrl: 'https://opencode.ai/docs',
  args: ['acp'],
  loginArgs: ['auth', 'login'],
  installDirs: (home) => [join(home, '.opencode', 'bin'), join(home, '.local', 'bin')],
  authMethod: () => undefined,
  signedIn: (_env, home) => existsSync(join(home, '.local', 'share', 'opencode', 'auth.json'))
}

export const gemini: AcpAgentSpec = {
  id: 'gemini',
  label: 'Gemini',
  command: 'gemini',
  installUrl: 'https://geminicli.com/docs/get-started/installation',
  args: ['--acp'],
  // Gemini signs in interactively on first run.
  loginArgs: [],
  installDirs: () => [],
  authMethod: (advertised, env) =>
    env.GEMINI_API_KEY?.trim() && advertised.includes('gemini-api-key')
      ? 'gemini-api-key'
      : advertised.includes('oauth-personal')
        ? 'oauth-personal'
        : undefined,
  signedIn: (env, home) => Boolean(env.GEMINI_API_KEY?.trim()) || existsSync(join(home, '.gemini', 'oauth_creds.json'))
}

const BUILT_IN = new Set(['claude', 'codex', 'grok', 'cursor', 'opencode', 'gemini'])

/** An ACP agent from `canopy.customAgents`: `{ id, label, command, args, loginArgs? }`. */
export function customAgent(entry: Record<string, unknown>): AcpAgentSpec | undefined {
  const { id, label, command, args, loginArgs } = entry
  const strings = (value: unknown) => (Array.isArray(value) && value.every((item) => typeof item === 'string') ? (value as string[]) : undefined)
  if (typeof id !== 'string' || !/^[a-z0-9-]+$/.test(id) || BUILT_IN.has(id)) return undefined
  if (typeof label !== 'string' || typeof command !== 'string' || !strings(args)) return undefined
  return {
    id,
    label,
    command,
    installUrl: 'https://agentclientprotocol.com/overview/agents',
    args: strings(args) ?? [],
    loginArgs: strings(loginArgs) ?? [],
    installDirs: () => [],
    authMethod: () => undefined,
    signedIn: () => true
  }
}
