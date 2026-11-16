import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join, posix } from 'node:path'
import test from 'node:test'
import ts from 'typescript'
import { browserModuleAssets } from './bundled-mermaid'

test('保留动态模块闭包与循环依赖，改用服务器可识别的 JS 扩展', t => {
  const root = mkdtempSync(join(tmpdir(), 'nexus-browser-modules-')); t.after(() => rmSync(root, { recursive: true, force: true }))
  mkdirSync(join(root, 'chunks'))
  writeFileSync(join(root, 'main.mjs'), 'export { value } from "./chunks/shared.mjs"; export const lazy=()=>import("./chunks/lazy.mjs");')
  writeFileSync(join(root, 'chunks/shared.mjs'), 'export const value=1; import "../main.mjs";')
  writeFileSync(join(root, 'chunks/lazy.mjs'), 'export const result=2;\n//# sourceMappingURL=lazy.mjs.map')
  const assets = browserModuleAssets(root, 'main.mjs')
  assert.deepEqual(assets.map(a => a.fileName).sort(), ['chunks/lazy.js', 'chunks/shared.js', 'main.js'])
  assert.match(assets.find(a => a.fileName === 'main.js')!.source, /import\("\.\/chunks\/lazy.js"\)/)
  assert.equal(assets.some(a => a.source.includes('sourceMappingURL')), false)
})
test('拒绝分发目录之外的依赖', t => {
  const root = mkdtempSync(join(tmpdir(), 'nexus-browser-modules-')); t.after(() => rmSync(root, { recursive: true, force: true }))
  writeFileSync(join(root, 'main.mjs'), 'import "../outside.mjs";')
  assert.throws(() => browserModuleAssets(root, 'main.mjs'), /outside_distribution/)
})
test('官方 Mermaid 浏览器发行包的全部相对模块引用都存在于发布闭包', () => {
  const require = createRequire(new URL('../workspace/package.json', import.meta.url))
  const root = dirname(require.resolve('mermaid'))
  const assets = browserModuleAssets(root, 'mermaid.esm.min.mjs'), names = new Set(assets.map(a => a.fileName))
  assert.ok(assets.length > 10)
  for (const asset of assets) {
    const tree = ts.createSourceFile(asset.fileName, asset.source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
    function visit(node: ts.Node) {
      let target: string | undefined
      if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) target = node.moduleSpecifier.text
      else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) target = node.arguments[0].text
      if (target?.startsWith('.')) assert.ok(names.has(posix.normalize(posix.join(posix.dirname(asset.fileName), target))), `${asset.fileName}: ${target}`)
      ts.forEachChild(node, visit)
    }
    visit(tree)
  }
  assert.match(readFileSync(join(root, 'mermaid.esm.min.mjs'), 'utf8'), /export/)
})
