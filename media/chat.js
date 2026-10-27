// @ts-check
const vscode = acquireVsCodeApi()
const log = /** @type {HTMLElement} */ (document.getElementById('log'))
const status = /** @type {HTMLElement} */ (document.getElementById('status'))
const signIn = /** @type {HTMLButtonElement} */ (document.getElementById('sign-in'))
const prompt = /** @type {HTMLTextAreaElement} */ (document.getElementById('prompt'))
const form = /** @type {HTMLFormElement} */ (document.getElementById('composer'))

/** @type {Map<string, HTMLElement>} */
const nodes = new Map()

function add(className, text) {
  const el = document.createElement('div')
  el.className = `item ${className}`
  el.textContent = text
  log.appendChild(el)
  el.scrollIntoView({ block: 'end' })
  return el
}

function summarize(input) {
  if (input && typeof input === 'object') {
    const value = input.file_path ?? input.command ?? input.pattern ?? input.path ?? input.url
    if (typeof value === 'string') return value
  }
  return JSON.stringify(input)
}

form.addEventListener('submit', (event) => {
  event.preventDefault()
  const text = prompt.value.trim()
  if (!text) return
  add('user', text)
  vscode.postMessage({ type: 'send', text })
  prompt.value = ''
})
prompt.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    form.requestSubmit()
  }
})
document.getElementById('stop')?.addEventListener('click', () => vscode.postMessage({ type: 'interrupt' }))
signIn.addEventListener('click', () => vscode.postMessage({ type: 'signIn' }))

window.addEventListener('message', ({ data }) => {
  switch (data.type) {
    case 'status':
      status.firstChild && (status.firstChild.textContent = data.text + ' ')
      signIn.hidden = data.signedIn
      return
    case 'init':
      add('meta', `${data.model} · auth: ${data.apiKeySource}`)
      return
    case 'text': {
      const node = nodes.get(data.id) ?? add('assistant', '')
      nodes.set(data.id, node)
      node.textContent += data.delta
      node.scrollIntoView({ block: 'end' })
      return
    }
    case 'tool':
      nodes.set(data.id, add('tool', `${data.name}: ${summarize(data.input)}`))
      return
    case 'tool_result': {
      const node = nodes.get(data.id)
      node?.classList.add(data.isError ? 'failed' : 'done')
      if (data.isError && node) node.textContent += `\n${data.text}`
      return
    }
    case 'permission': {
      const node = add('permission', `Allow ${data.toolName}: ${summarize(data.input)}?`)
      for (const [label, allow] of [['Allow', true], ['Deny', false]]) {
        const button = document.createElement('button')
        button.textContent = /** @type {string} */ (label)
        button.addEventListener('click', () => {
          vscode.postMessage({ type: 'permission', id: data.id, allow })
          node.querySelectorAll('button').forEach((b) => b.remove())
          node.append(allow ? ' — allowed' : ' — denied')
        })
        node.appendChild(button)
      }
      return
    }
    case 'turn_end':
      add('meta', `turn finished in ${(data.durationMs / 1000).toFixed(1)}s${data.isError ? ' (error)' : ''}`)
      return
    case 'error':
      add('error', data.message)
      return
  }
})

vscode.postMessage({ type: 'ready' })
