/** 按应用串行启动 Playwright，避免两个 Vite 依赖优化器同时争用内存。 */
import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
const require = createRequire(import.meta.url)
const cli = join(dirname(require.resolve('@playwright/test/package.json')), 'cli.js')
const args = process.argv.slice(2)
const preview = args[0] === 'preview'
if (preview) args.shift()
const selected = args[0] && !args[0].startsWith('-') ? args.shift() : undefined
if (selected && !['enterprise', 'workspace'].includes(selected)) throw new Error('Expected app: enterprise or workspace')
const apps = selected ? [selected] : ['workspace', 'enterprise']
for (const app of apps) {
  const child = spawn(process.execPath, [cli, 'test', `--project=${app}`, ...args], {
    stdio: 'inherit', env: { ...process.env, NEXUS_E2E_APP: app, ...(preview ? { NEXUS_E2E_PREVIEW: '1' } : {}) },
  })
  // 交给 Playwright 关闭自己启动的服务；不扫描或终止其他开发进程。
  const stop = signal => child.kill(signal)
  const interrupt = () => stop('SIGINT'), terminate = () => stop('SIGTERM')
  process.once('SIGINT', interrupt); process.once('SIGTERM', terminate)
  const code = await new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', (code, signal) => resolve(code ?? (signal === 'SIGINT' ? 130 : 1))) })
  process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', terminate)
  if (code !== 0) process.exit(code)
}
