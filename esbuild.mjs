import { execFileSync } from 'node:child_process'
import { cpSync, mkdirSync, rmSync } from 'node:fs'
import * as esbuild from 'esbuild'

const watch = process.argv.includes('--watch')
const preview = process.argv.includes('--preview')

const extension = {
  entryPoints: { 'smoke-switch': 'scripts/smoke-switch.ts', driver: 'scripts/driver.ts', 'smoke-group': 'scripts/smoke-group.ts', 'smoke-delegate': 'scripts/smoke-delegate.ts', 'smoke-commit': 'scripts/smoke-commit.ts', 'poc-stream': 'poc/capture-stream.ts', 'poc-frames': 'poc/frames.ts', 'poc-settle': 'poc/settle-live.ts', 'poc-tools': 'poc/probe-tools.ts', 'poc-group': 'poc/group.ts', extension: 'src/extension.ts', smoke: 'scripts/smoke.ts', 'smoke-prompts': 'scripts/smoke-prompts.ts', 'smoke-lanes': 'scripts/smoke-lanes.ts', 'smoke-boundary': 'scripts/smoke-boundary.ts', 'smoke-steer': 'scripts/smoke-steer.ts', 'smoke-rewind': 'scripts/smoke-rewind.ts', 'record-claude': 'scripts/record-claude.ts', 'record-codex': 'scripts/record-codex.ts', 'record-grok': 'scripts/record-grok.ts' },
  outdir: 'dist',
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node20',
  sourcemap: true,
  // The Agent SDK is ESM and reads import.meta.url, which a CJS bundle lacks; point it at the bundle file.
  define: { 'import.meta.url': '__importMetaUrl' },
  banner: { js: 'const __importMetaUrl = require("url").pathToFileURL(__filename).href;' },
  external: ['vscode']
}

const webview = {
  entryPoints: { main: 'webview/main.tsx' },
  outdir: 'dist/webview',
  bundle: true,
  format: 'esm',
  // Shiki's grammars load on demand as separate chunks instead of inflating the entry script.
  splitting: true,
  platform: 'browser',
  target: 'chrome120',
  jsx: 'automatic',
  tsconfig: 'webview/tsconfig.json',
  entryNames: '[name]',
  chunkNames: 'chunks/[name]-[hash]',
  minify: !watch,
  sourcemap: watch,
  define: { 'process.env.NODE_ENV': watch ? '"development"' : '"production"' }
}

// Classic scripts, so the preview page works from a file:// URL in headless Chromium.
const previewBuild = {
  ...webview,
  entryPoints: { main: 'webview/main.tsx', scenario: 'webview/preview/scenario.ts' },
  outdir: 'dist/preview',
  format: 'iife',
  splitting: false,
  minify: false
}

function styles(outdir) {
  mkdirSync(outdir, { recursive: true })
  execFileSync('node_modules/.bin/tailwindcss', ['-i', 'webview/theme.css', '-o', `${outdir}/webview.css`, '--minify'], {
    stdio: 'inherit'
  })
  cpSync('node_modules/@vscode/codicons/dist/codicon.css', `${outdir}/codicon.css`)
  cpSync('node_modules/@vscode/codicons/dist/codicon.ttf', `${outdir}/codicon.ttf`)
  cpSync('node_modules/katex/dist/katex.min.css', `${outdir}/katex.css`)
  cpSync('node_modules/katex/dist/fonts', `${outdir}/fonts`, { recursive: true })
}

if (preview) {
  rmSync('dist/preview', { recursive: true, force: true })
  await esbuild.build(previewBuild)
  styles('dist/preview')
  cpSync('webview/preview/index.html', 'dist/preview/index.html')
  cpSync('webview/preview/themes.css', 'dist/preview/themes.css')
} else if (watch) {
  styles('dist/webview')
  await (await esbuild.context(extension)).watch()
  await (await esbuild.context(webview)).watch()
} else {
  // Chunk names carry hashes, so stale chunks would pile up without a clean build.
  rmSync('dist/webview', { recursive: true, force: true })
  await Promise.all([esbuild.build(extension), esbuild.build(webview)])
  styles('dist/webview')
}
