import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
const source = readFileSync(new URL('./OrganizationSettingsModal.vue', import.meta.url), 'utf8')
const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)![1]!
const tree = ts.createSourceFile('OrganizationSettingsModal.ts', script, ts.ScriptTarget.Latest, true)
const statement = tree.statements.find(node => ts.isVariableStatement(node) && node.declarationList.declarations.some(d => ts.isIdentifier(d.name) && d.name.text === 'isOwnerMember'))
assert.ok(statement)
const js = ts.transpileModule(statement.getText(tree), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText

test('共享空间所有者按企业 UUID 识别；只有未回填企业时才使用旧用户归属', () => {
  const tenant = '123e4567-e89b-12d3-a456-426614174000'
  const orgInfo: { value: { owner_tenant_id?: string; owner_id: string } } = { value: { owner_tenant_id: tenant, owner_id: 'legacy-owner' } }
  const owner = runInNewContext(`${js}\nisOwnerMember`, { orgInfo })
  assert.equal(owner({ tenant_id: tenant, user_id: 'another-member' }), true)
  assert.equal(owner({ tenant_id: 'other-tenant', user_id: 'legacy-owner' }), false)
  orgInfo.value = { owner_id: 'legacy-owner' }
  assert.equal(owner({ tenant_id: tenant, user_id: 'legacy-owner' }), true)
  assert.equal(owner({ tenant_id: tenant, user_id: 'another-member' }), false)
})
