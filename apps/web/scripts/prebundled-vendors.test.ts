import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { pathToFileURL } from 'node:url'
import test from 'node:test'
import { prebundledVendors } from './prebundled-vendors'

test('独立预打包保留导出与普通字符串，并与应用复用唯一 Vue 模块', async t => {
  const root = mkdtempSync(join(tmpdir(), 'nexus-vendors-')); t.after(() => rmSync(root, { recursive: true, force: true }))
  writeFileSync(join(root, 'package.json'), '{"type":"module"}')
  const vendor = (name: string, source: string) => {
    const entry = join(root, `${name}.js`); writeFileSync(entry, source)
    return { name, entry, version: '1' }
  }
  const vue = vendor('vue', 'export const token = Symbol("one runtime");')
  const demi = vendor('vue-demi', 'export * from "vue";')
  const library = vendor('example', 'import { token } from "vue-demi"; export const text="vue"; export const value=token; export default token;')
  const unused = vendor('unused', 'export const unused=true;')
  const plugin = prebundledVendors(vue, demi, [library, unused])
  // 调用真实构建钩子，随后通过 Node ESM 执行发布资产，而非只比对源字符串。
  const resolved = plugin.configResolved as (config: { base: string }) => void
  const start = plugin.buildStart as () => Promise<void>
  const resolve = plugin.resolveId as (name: string) => { id: string } | undefined
  const emit = plugin.generateBundle as (this: { emitFile: (file: { fileName: string; source: string }) => void }) => void
  resolved({ base: `${pathToFileURL(root).href}/` }); await start()
  const source = resolve(library.name)!, shared = resolve('vue')!
  const files: string[] = []
  emit.call({ emitFile(file) { files.push(file.fileName); const path = join(root, file.fileName); mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, file.source) } })
  assert.equal(files.some(f => f.includes('unused')), false)
  const actual = await import(source.id), runtime = await import(shared.id)
  assert.equal(actual.default, runtime.token); assert.equal(actual.value, runtime.token)
  assert.equal(actual.text, 'vue')
})
