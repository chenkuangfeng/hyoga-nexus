/** 将已发布的重型浏览器依赖独立预打包为同源 ESM，降低主 Rollup 构建的 AST 峰值。 */
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { build } from 'esbuild'
import type { Plugin } from 'vite'

export interface BrowserVendor { name: string; version: string; entry: string }
const digest = (source: string) => createHash('sha256').update(source).digest('hex').slice(0, 12)
/** 主应用和独立预打包依赖必须复用同一个官方 Vue 浏览器运行时。 */
export function prebundledVendors(vue: BrowserVendor, demi: BrowserVendor, vendors: BrowserVendor[]): Plugin {
  let base = '/'
  const used = new Set<string>()
  const assets = new Map<string, { fileName: string; source: string }>()
  const fileName = (vendor: BrowserVendor, source: string) => `assets/vendor/${vendor.name.replace(/[^a-zA-Z0-9._-]/g, '-')}-${vendor.version}-${digest(source)}.js`
  const url = (name: string) => `${base}${assets.get(name)!.fileName}`
  async function bundle(vendor: BrowserVendor) {
    const result = await build({
      entryPoints: [vendor.entry], bundle: true, write: false, format: 'esm',
      platform: 'browser', target: 'es2022', minify: true, metafile: true,
      plugins: [{ name: 'shared-vue-runtime', setup(bundler) {
        bundler.onResolve({ filter: /^(vue|vue-demi)$/ }, args => ({ path: url(args.path), external: true }))
      } }], define: { 'process.env.NODE_ENV': '"production"' },
      loader: { '.css': 'empty' }, logLevel: 'silent',
    })
    // TDesign 的完整 CSS 仍由两应用 main.ts 导入并交给 Vite 处理，不重复封入 JS。
    if (vendor.name !== 'tdesign-vue-next' && Object.keys(result.metafile.inputs).some(id => id.endsWith('.css'))) {
      throw new Error(`unexpected_vendor_css:${vendor.name}`)
    }
    // 不允许把第二份 Vue 响应式运行时封入任一依赖。
    if (Object.keys(result.metafile.inputs).some(id => /[\\/]@vue[\\/](reactivity|runtime-core|runtime-dom)[\\/]/.test(id))) {
      throw new Error(`duplicate_vue_runtime_in_vendor:${vendor.name}`)
    }
    const source = result.outputFiles[0]!.text
    assets.set(vendor.name, { fileName: fileName(vendor, source), source })
  }
  return {
    name: 'prebundled-browser-vendors', apply: 'build', enforce: 'pre',
    configResolved(config) { base = config.base },
    async buildStart() {
      assets.clear(); used.clear()
      const source = readFileSync(vue.entry, 'utf8')
      assets.set('vue', { fileName: fileName(vue, source), source })
      await bundle(demi)
      // 串行处理，避免预打包器与主构建同时保留所有库的语法树。
      for (const vendor of vendors) await bundle(vendor)
    },
    resolveId(source) {
      const name = assets.has(source) ? source : vendors.find(vendor => vendor.entry.replaceAll('\\', '/') === source.replaceAll('\\', '/'))?.name
      if (!name) return
      used.add(name)
      if (name.endsWith('?worker&url')) return { id: `\0nexus-vendor-url:${name}` }
      return { id: url(name), external: 'absolute' }
    },
    load(id) {
      if (id.startsWith('\0nexus-vendor-url:')) return `export default ${JSON.stringify(url(id.slice('\0nexus-vendor-url:'.length)))}`
    },
    generateBundle() {
      // 所有依赖共享 Vue/VueDemi；其余只发布应用实际引用的库。
      if (used.size) { used.add('vue'); used.add('vue-demi') }
      for (const name of used) this.emitFile({ type: 'asset', ...assets.get(name)! })
    },
    moduleParsed(info) {
      if (/[\\/]@vue[\\/](reactivity|runtime-core|runtime-dom)[\\/]/.test(info.id)) throw new Error('duplicate_vue_runtime_in_application')
    },
  }
}
