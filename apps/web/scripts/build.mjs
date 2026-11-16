/** 两应用串行构建，并给 Node/esbuild 设置可由环境覆盖的内存默认值。 */
import { spawn } from 'node:child_process'
import { constants } from 'node:os'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const require = createRequire(import.meta.url), web = fileURLToPath(new URL('..', import.meta.url))
const cli = join(dirname(require.resolve('vite/package.json')), 'bin/vite.js')
const selected = process.argv[2]
if (selected && !['workspace', 'admin'].includes(selected)) throw new Error('Expected workspace or admin')
for (const app of selected ? [selected] : ['workspace', 'admin']) {
  const child = spawn(process.execPath, [cli, 'build', '--config', join(web, app, 'vite.config.ts')], {
    cwd: web, stdio: 'inherit', env: { ...process.env,
      NODE_OPTIONS: process.env.NODE_OPTIONS || '--max-old-space-size=768 --max-semi-space-size=4',
      GOMEMLIMIT: process.env.GOMEMLIMIT || '192MiB', GOMAXPROCS: process.env.GOMAXPROCS || '2',
      MALLOC_ARENA_MAX: process.env.MALLOC_ARENA_MAX || '2',
    },
  })
  const interrupt = () => child.kill('SIGINT'), terminate = () => child.kill('SIGTERM')
  process.once('SIGINT', interrupt); process.once('SIGTERM', terminate)
  const result = await new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', (code, signal) => resolve({ code, signal })) })
  process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', terminate)
  if (result.signal) console.error(`子进程被 ${result.signal} 终止`)
  const code = result.code ?? (128 + (constants.signals[result.signal] || 0))
  if (code) process.exit(code)
}
