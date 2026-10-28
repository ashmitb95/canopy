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
