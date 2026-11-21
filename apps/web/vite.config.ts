import { fileURLToPath, URL } from 'node:url'
import { resolve, dirname } from 'node:path'
import { existsSync, readFileSync } from 'node:fs'
import { execSync } from 'node:child_process'
import { copyPdfJsWasm } from './scripts/copy-pdfjs-wasm.mjs'
import { bundledMermaid } from './scripts/bundled-mermaid'
import { prebundledVendors, type BrowserVendor } from './scripts/prebundled-vendors'
import { buildBoundaries } from './scripts/build-boundaries'
import { createRequire } from 'node:module'
import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'

const __dirname = dirname(fileURLToPath(import.meta.url))
// 预览依赖随员工应用安装，配置工厂从该项目解析，避免 workspace 根的幽灵依赖。
const require = createRequire(resolve(__dirname, 'workspace/package.json'))

const pkg = require('./package.json') as { version?: string }
const FRONTEND_VERSION = pkg.version ?? 'unknown'

function resolveFrontendCommit(): string {
  const fromEnv = process.env.VITE_FRONTEND_COMMIT || process.env.GITHUB_SHA
  if (fromEnv) {
    return fromEnv.slice(0, 7)
  }
  try {
    return execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim()
  } catch {
    return 'unknown'
  }
}

const FRONTEND_COMMIT = resolveFrontendCommit()

/** Dev parity with nginx: serve embed.html for /embed/:channelId (not the main SPA). */
function embedHtmlDevFallback(): Plugin {
  return {
    name: 'embed-html-dev-fallback',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const raw = req.url ?? ''
        const qIdx = raw.indexOf('?')
        const path = qIdx >= 0 ? raw.slice(0, qIdx) : raw
        const qs = qIdx >= 0 ? raw.slice(qIdx) : ''
        if (path.startsWith('/embed/') && path !== '/embed.html' && !path.includes('.')) {
          req.url = `/embed.html${qs}`
        }
        next()
      })
    },
  }
}
const DEV_PROXY_TARGET =
  process.env.VITE_DEV_PROXY_TARGET ||
  process.env.FRONTEND_BACKEND_URL ||
  'http://127.0.0.1:8000'
const ENTERPRISE_DEV_TARGET = process.env.NEXUS_ENTERPRISE_DEV_TARGET || 'http://127.0.0.1:5174'
const ENTERPRISE_PREVIEW_TARGET = process.env.NEXUS_ENTERPRISE_PREVIEW_TARGET || 'http://127.0.0.1:4174'

function resolveVueOfficePptxEntry(): string {
  try {
    const pkgDir = dirname(require.resolve('@vue-office/pptx/package.json'))
    const candidates = [
      // Use ESM so setup hooks and render helpers share the application's Vue
      // runtime. The UMD entry's require('vue') can produce a second runtime in
      // Vite's dev optimizer, leaving template refs null and PPTX previews blank.
      resolve(pkgDir, 'lib/v3/vue-office-pptx.mjs'),
      resolve(pkgDir, 'lib/v3/index.js'),
      resolve(pkgDir, 'lib/index.js'),
    ]
    const matched = candidates.find((candidate) => existsSync(candidate))
    return matched ?? '@vue-office/pptx'
  } catch {
    return '@vue-office/pptx'
  }
}

function pdfJsWasmAssets(): Plugin {
  let wasmSource = ''
  let wasmOutput = ''
  return {
    name: 'pdfjs-wasm-assets',
    apply: 'build',
    configResolved(config) {
      const pdfjsBuild = require.resolve('pdfjs-dist/legacy/build/pdf.mjs')
      wasmSource = resolve(dirname(pdfjsBuild), '../../wasm')
      wasmOutput = resolve(config.root, config.build.outDir, 'pdfjs', 'wasm')
    },
    closeBundle() {
      copyPdfJsWasm(wasmSource, wasmOutput)
    },
  }
}

/** 使用依赖自身的 ESM 入口，保留全部导出；VueOffice 明确使用同一 Vue 3 入口。 */
function browserImportEntry(value: unknown): string | undefined {
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object' || Array.isArray(value)) return
  const conditions = value as Record<string, unknown>
  for (const key of ['browser', 'import', 'default']) {
    const entry = browserImportEntry(conditions[key])
    if (entry) return entry
  }
}

function browserVendor(name: string, entry?: string): BrowserVendor {
  // 某些发行包不导出 package.json，从真实入口向上定位其清单。
  let directory = dirname(require.resolve(name))
  while (true) {
    const path = resolve(directory, 'package.json')
    if (existsSync(path)) {
      const manifest = JSON.parse(readFileSync(path, 'utf8')) as { name: string; version: string; module?: string; exports?: unknown }
      if (manifest.name === name) {
        const exports = manifest.exports && typeof manifest.exports === 'object' ? manifest.exports as Record<string, unknown> : undefined
        const module = browserImportEntry(exports?.['.'] ?? manifest.exports) || manifest.module
        return { name, version: manifest.version, entry: entry || (module ? resolve(directory, module) : require.resolve(name)) }
      }
    }
    const parent = dirname(directory)
    if (parent === directory) throw new Error(`browser_vendor_manifest_missing:${name}`)
    directory = parent
  }
}

/** 创建共享构建配置，保持两个应用的独立入口、部署路径和相同的 API 代理行为。 */
export function createWebConfig(app: 'workspace' | 'enterprise') {
  const appRoot = resolve(__dirname, app)
  return defineConfig({
    root: appRoot,
    base: app === 'enterprise' ? '/enterprise/' : '/',
    publicDir: resolve(__dirname, 'workspace/public'),
    optimizeDeps: { exclude: ['@nexus-web/core'] },
    define: {
      __FRONTEND_VERSION__: JSON.stringify(FRONTEND_VERSION),
      __FRONTEND_COMMIT__: JSON.stringify(FRONTEND_COMMIT),
    },
    build: {
      modulePreload: {
        resolveDependencies(_filename, deps, { hostId }) {
          // Embed iframe bootstraps with token exchange only; defer heavy chat chunks.
          if (hostId?.includes('embed')) {
            return deps.filter((dep) => !(
              dep.includes('vendor-mermaid')
              || dep.includes('vendor-highlight')
              || dep.includes('vendor-markdown')
              || dep.includes('vendor-tdesign')
              || dep.includes('botmsg')
              || dep.includes('usermsg')
              || dep.includes('EmbedBotMessage')
              || dep.includes('EmbedUserMessage')
              || dep.includes('AgentStreamDisplay')
              || dep.includes('EmbedChatCore')
              || dep.includes('vendor-markdown')
              || dep.includes('fonts-')
            ))
          }
          return deps
        },
      },
      rollupOptions: {
        input: app === 'workspace' ? {
          main: resolve(appRoot, 'index.html'),
          embed: resolve(appRoot, 'embed.html'),
        } : { main: resolve(appRoot, 'index.html') },
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) return
            if (id.includes('mermaid') || id.includes('/dagre') || id.includes('cytoscape')) {
              return 'vendor-mermaid'
            }
            if (id.includes('marked') || id.includes('katex')) {
              return 'vendor-markdown'
            }
            if (id.includes('highlight.js')) {
              return 'vendor-highlight'
            }
          },
        },
      },
    },
    plugins: [
      vue(),
      vueJsx(),
      embedHtmlDevFallback(),
      pdfJsWasmAssets(),
      buildBoundaries(__dirname, app),
      bundledMermaid(dirname(require.resolve('mermaid')), (require('mermaid/package.json') as { version: string }).version),
      prebundledVendors(
        browserVendor('vue', resolve(dirname(require.resolve('vue/package.json')), 'dist/vue.runtime.esm-browser.prod.js')),
        browserVendor('vue-demi'),
        [browserVendor('tdesign-vue-next'), browserVendor('highlight.js'), browserVendor('katex'),
          browserVendor('xlsx'), browserVendor('@vue-office/pptx', resolveVueOfficePptxEntry()),
          { ...browserVendor('pdfjs-dist', require.resolve('pdfjs-dist/legacy/build/pdf.mjs')), name: 'pdfjs-dist/legacy/build/pdf.mjs' },
          { ...browserVendor('pdfjs-dist', require.resolve('pdfjs-dist/legacy/build/pdf.worker.min.mjs')), name: 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?worker&url' }],
      ),
    ],
    resolve: {
      dedupe: ['vue', 'vue-demi'],
      alias: {
        '@': resolve(appRoot, 'src'),
        '@nexus-web/core': resolve(__dirname, 'core/src'),
        '@vue-office/pptx': resolveVueOfficePptxEntry(),
      },
    },
    server: {
      port: app === 'enterprise' ? 5174 : 5173,
      host: true,
      // 代理配置，用于开发环境
      proxy: {
        // 保持工作台与企业管理同源，让新页面直接校验当前会话和空间。
        ...(app === 'workspace' ? { '/enterprise/': { target: ENTERPRISE_DEV_TARGET, ws: true } } : {}),
        '/mcp/': {
          target: DEV_PROXY_TARGET,
          changeOrigin: true,
          secure: false,
          // Streamable HTTP may keep an SSE response open for long-running tools.
          timeout: 3_600_000,
          proxyTimeout: 3_600_000,
        },
        '/api': {
          target: DEV_PROXY_TARGET,
          changeOrigin: true,
          secure: false,
          // 沙箱终端等 WebSocket 升级请求也走 /api，必须开启 WS 转发，
          // 否则浏览器侧握手失败、前端表现为"一直正在连接"。
          ws: true,
          // Cube fork snapshots pause a live MicroVM; 30s axios/proxy defaults
          // abort the POST and the backend then 500s on a canceled persist.
          timeout: 180_000,
          proxyTimeout: 180_000,
        },
        '/files': {
          target: DEV_PROXY_TARGET,
          changeOrigin: true,
          secure: false,
        }
      }
    },
    // `vite preview` 用生产构建产物(dist)本地起服务，是最接近 release 镜像的环境：
    // 同样的压缩 / 拆包 / CSS 加载顺序，可提前暴露只在生产构建出现的问题
    // （如主题变量被打包顺序覆盖）。用法：npm run build && npm run preview
    preview: {
      port: app === 'enterprise' ? 4174 : 4173,
      host: true,
      proxy: {
        ...(app === 'workspace' ? { '/enterprise/': { target: ENTERPRISE_PREVIEW_TARGET } } : {}),
        '/mcp/': {
          target: DEV_PROXY_TARGET,
          changeOrigin: true,
          secure: false,
          timeout: 3_600_000,
          proxyTimeout: 3_600_000,
        },
        '/api': {
          target: DEV_PROXY_TARGET,
          changeOrigin: true,
          secure: false,
          ws: true,
          timeout: 180_000,
          proxyTimeout: 180_000,
        },
        '/files': {
          target: DEV_PROXY_TARGET,
          changeOrigin: true,
          secure: false,
        }
      }
    }
  })
}
