/** 发布 Mermaid 官方浏览器 ESM 分发文件，避免 Rollup 为已打包依赖重建庞大 AST。 */
import { readFileSync } from 'node:fs'
import { dirname, isAbsolute, relative, resolve } from 'node:path'
import type { Plugin } from 'vite'

export interface BrowserModuleAsset { fileName: string; source: string }
/**
 * 读取官方 ESM 图的相对 .mjs 依赖闭包，改名为普通 .js 以兼容静态服务器 MIME。
 * 不改变运行逻辑或裁剪功能；发现越过分发目录的引用即失败。输入须为本地可信分发文件。
 */
export function browserModuleAssets(root: string, entry: string): BrowserModuleAsset[] {
  const result: BrowserModuleAsset[] = [], visited = new Set<string>()
  function visit(file: string) {
    const sourcePath = resolve(root, file), name = relative(root, sourcePath).replaceAll('\\', '/')
    if (name.startsWith('../') || isAbsolute(name)) throw new Error('browser_module_outside_distribution')
    if (visited.has(name)) return
    visited.add(name)
    // 官方 esbuild 分发使用静态字符串指向相对 .mjs；同时覆盖静态与动态 import。
    const source = readFileSync(sourcePath, 'utf8').replace(/(["'])(\.{1,2}\/[^"'\n]+\.mjs)\1/g, (_all, quote: string, target: string) => {
      visit(relative(root, resolve(dirname(sourcePath), target)))
      return `${quote}${target.slice(0, -4)}.js${quote}`
    }).replace(/\/\/# sourceMappingURL=[^\n]*/g, '')
    result.push({ fileName: name.replace(/\.mjs$/, '.js'), source })
  }
  visit(entry)
  return result
}
/** 仅在构建实际使用 Mermaid 时发布资产，解析器仍在浏览器按需加载。 */
export function bundledMermaid(root: string, version: string): Plugin {
  const directory = `assets/mermaid-${version}`
  let base = '/', used = false
  return {
    name: 'bundled-mermaid', apply: 'build', enforce: 'pre',
    configResolved(config) { base = config.base },
    resolveId(source) {
      if (source !== 'mermaid') return
      used = true
      return { id: `${base}${directory}/mermaid.esm.min.js`, external: 'absolute' }
    },
    generateBundle() {
      if (!used) return
      for (const asset of browserModuleAssets(root, 'mermaid.esm.min.mjs')) {
        this.emitFile({ type: 'asset', fileName: `${directory}/${asset.fileName}`, source: asset.source })
      }
    },
  }
}
