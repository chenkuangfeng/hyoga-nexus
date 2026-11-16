import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'

const source = readFileSync(new URL('./UserMenu.vue', import.meta.url), 'utf8')
const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)![1]!
const tree = ts.createSourceFile('UserMenu.ts', script, ts.ScriptTarget.Latest, true)
const statement = tree.statements.find(node => ts.isVariableStatement(node) && node.declarationList.declarations.some(d => ts.isIdentifier(d.name) && d.name.text === 'isCurrentTenant'))
assert.ok(statement)
const js = ts.transpileModule(statement.getText(tree), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText

test('企业 UUID 直接比较，切换后只标记当前企业，不做数值转换', () => {
  const a = '123e4567-e89b-12d3-a456-426614174000', b = '223e4567-e89b-12d3-a456-426614174000'
  const authStore: { effectiveTenantId: string | null } = { effectiveTenantId: a }
  const current = runInNewContext(`${js}\nisCurrentTenant`, { authStore })
  assert.equal(current(a), true); assert.equal(current(b), false)
  authStore.effectiveTenantId = b
  assert.equal(current(a), false); assert.equal(current(b), true)
  authStore.effectiveTenantId = null
  assert.equal(current(a), false)
})
