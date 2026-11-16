/** 串行运行原生 vue-tsc 工程；每个进程结束后释放虚拟模板缓存。 */
import { spawn } from 'node:child_process'
import { constants } from 'node:os'
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const require = createRequire(import.meta.url), web = fileURLToPath(new URL('..', import.meta.url))
const cli = join(dirname(require.resolve('vue-tsc/package.json')), 'bin/vue-tsc.js')
const selected = process.argv[2]
if (selected && !['core', 'workspace', 'admin'].includes(selected)) throw new Error('Expected core, workspace or admin')
const options = process.env.NODE_OPTIONS || '--max-old-space-size=768 --max-semi-space-size=4'
async function run(args) {
  const child = spawn(process.execPath, args, { cwd: web, stdio: 'inherit', env: { ...process.env, NODE_OPTIONS: options, MALLOC_ARENA_MAX: process.env.MALLOC_ARENA_MAX || '2' } })
  const interrupt = () => child.kill('SIGINT'), terminate = () => child.kill('SIGTERM')
  process.once('SIGINT', interrupt); process.once('SIGTERM', terminate)
  const result = await new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', (code, signal) => resolve({ code, signal })) })
  process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', terminate)
  if (result.signal) console.error(`子进程被 ${result.signal} 终止`)
  const code = result.code ?? (128 + (constants.signals[result.signal] || 0))
  if (code) process.exit(code)
}
await run([cli, '--build', 'core/tsconfig.types.json'])
await run([join(web, 'scripts/verify-type-resolution.mjs'), 'core'])
for (const app of selected === 'core' ? [] : selected ? [selected] : ['workspace', 'admin']) {
  await run([join(web, 'scripts/type-projects.mjs'), app])
  const manifest = JSON.parse(readFileSync(join(web, app, 'node_modules/.cache/nexus-types/manifest.json'), 'utf8'))
  for (const [i, project] of manifest.projects.entries()) {
    console.log(`${app}: ${i + 1}/${manifest.projects.length}`)
    await run([cli, '--build', project])
  }
  await run([join(web, 'scripts/verify-type-resolution.mjs'), app])
}
