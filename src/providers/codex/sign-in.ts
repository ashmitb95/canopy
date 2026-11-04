import type { SignInEvent, SignInFlow } from '../../core/types'
import type { Env } from '../../env'
import { spawnGroup, stopGroup } from '../../process'
import { RpcPeer } from '../rpc'

/** Codex's app-server runs the ChatGPT login itself and reports the link to open. */
export async function codexSignIn(cliPath: string, env: Env, onEvent: (event: SignInEvent) => void): Promise<SignInFlow> {
  const child = spawnGroup(cliPath, ['app-server'], { env, stdio: ['pipe', 'pipe', 'pipe'] })
  const rpc = new RpcPeer(child.stdout!, child.stdin!)
  let finished = false
  const finish = (event: SignInEvent | undefined) => {
    if (finished) return
    finished = true
    if (event) onEvent(event)
    void stopGroup(child)
  }
  rpc.onNotification(({ method, params }) => {
    if (method !== 'account/login/completed') return
    const { success, error } = params as { success: boolean; error: string | null }
    finish(success ? { kind: 'done' } : { kind: 'failed', message: error ?? 'Sign-in did not complete.' })
  })
  child.on('exit', () => finish({ kind: 'failed', message: 'Codex stopped before sign-in completed.' }))
  try {
    await rpc.request('initialize', {
      clientInfo: { name: 'canopy', title: 'Canopy', version: '1.0.0' },
      capabilities: { experimentalApi: true, requestAttestation: false }
    })
    rpc.notify('initialized')
    const { loginId, authUrl } = await rpc.request<{ loginId: string; authUrl: string }>('account/login/start', { type: 'chatgpt' })
    onEvent({ kind: 'link', url: authUrl })
    return {
      cancel: () => {
        if (finished) return
        void rpc.request('account/login/cancel', { loginId }).catch(() => undefined).finally(() => finish(undefined))
      }
    }
  } catch (error) {
    finish(undefined)
    throw error
  }
}
