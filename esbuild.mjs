import * as esbuild from 'esbuild'

const watch = process.argv.includes('--watch')

const options = {
  entryPoints: { extension: 'src/extension.ts', smoke: 'scripts/smoke.ts', 'record-claude': 'scripts/record-claude.ts' },
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

if (watch) {
  await (await esbuild.context(options)).watch()
} else {
  await esbuild.build(options)
}
