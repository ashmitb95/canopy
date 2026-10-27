import * as esbuild from 'esbuild'

const watch = process.argv.includes('--watch')

const options = {
  entryPoints: { extension: 'src/extension.ts', smoke: 'scripts/smoke.ts' },
  outdir: 'dist',
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node20',
  sourcemap: true,
  // The SDK is ESM-only and loaded at runtime with import(); vscode is provided by the host.
  external: ['vscode', '@anthropic-ai/claude-agent-sdk']
}

if (watch) {
  await (await esbuild.context(options)).watch()
} else {
  await esbuild.build(options)
}
