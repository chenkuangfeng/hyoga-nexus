import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'

function setup(options: { native?: 'ok' | 'reject'; fallbackFails?: boolean }) {
  let removed = false, focused = false, created = 0, copied = ''
  const node = { value: '', style: {}, focus() {}, select() {}, remove() { removed = true } }
  const exports: Record<string, any> = {}
  runInNewContext(ts.transpileModule(readFileSync(new URL('./clipboard.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, {
    exports, navigator: options.native ? { clipboard: { writeText: async (value: string) => { if (options.native === 'reject') throw new Error('denied'); copied = value } } } : {},
    document: { activeElement: { focus() { focused = true } }, body: { appendChild() {} }, createElement() { created++; return node }, execCommand() { if (options.fallbackFails) throw new Error('failed'); copied = node.value; return true } },
    require(name: string) { if (name === 'tdesign-vue-next') return { MessagePlugin: {} }; return { default: {} } },
  })
  return { api: exports, node, removed: () => removed, focused: () => focused, created: () => created, copied: () => copied }
}

test('现代剪贴板成功时不创建隐藏节点', async () => {
  const s = setup({ native: 'ok' })
  assert.equal(await s.api.copyToClipboard('link-token'), true)
  assert.equal(s.copied(), 'link-token'); assert.equal(s.created(), 0)
})
test('权限拒绝后降级复制，并清空节点、移除 DOM 与恢复焦点', async () => {
  const s = setup({ native: 'reject' })
  assert.equal(await s.api.copyToClipboard('link-token'), true)
  assert.equal(s.copied(), 'link-token'); assert.equal(s.node.value, '')
  assert.equal(s.removed(), true); assert.equal(s.focused(), true)
})
test('降级复制抛错也不会留下含令牌的隐藏节点', async () => {
  const s = setup({ fallbackFails: true })
  assert.equal(await s.api.copyToClipboard('link-token'), false)
  assert.equal(s.node.value, ''); assert.equal(s.removed(), true); assert.equal(s.focused(), true)
})
