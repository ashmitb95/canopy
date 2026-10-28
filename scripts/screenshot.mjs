// Renders dist/preview in headless Chromium and writes a PNG, so UI changes can be reviewed without VS Code.
import { execFileSync } from 'node:child_process'
import { existsSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'

const [theme = 'dark', size = '900x1200'] = process.argv.slice(2)
const [width, height] = size.split('x')
const out = resolve(`dist/preview/screenshot-${theme}.png`)
const browser = process.env.AGENTDECK_CHROME ?? findHeadlessShell()
if (!browser) {
  console.error('No headless Chromium found. Run `npx playwright install chromium-headless-shell` or set AGENTDECK_CHROME.')
  process.exit(1)
}
execFileSync(
  browser,
  [
    '--headless',
    '--disable-gpu',
    '--hide-scrollbars',
    `--screenshot=${out}`,
    `--window-size=${width},${height}`,
    '--virtual-time-budget=5000',
    `file://${resolve('dist/preview/index.html')}?theme=${theme}`
  ],
  { stdio: 'ignore' }
)
console.log(out)

function findHeadlessShell() {
  const cache =
    process.platform === 'darwin' ? join(homedir(), 'Library/Caches/ms-playwright') : join(homedir(), '.cache/ms-playwright')
  if (!existsSync(cache)) return undefined
  const name = process.platform === 'win32' ? 'chrome-headless-shell.exe' : 'chrome-headless-shell'
  const dirs = readdirSync(cache)
    .filter((dir) => dir.startsWith('chromium_headless_shell'))
    .sort()
    .reverse()
  for (const dir of dirs) {
    const match = readdirSync(join(cache, dir), { recursive: true }).find((file) => String(file).endsWith(name))
    if (match) return join(cache, dir, String(match))
  }
  return undefined
}
