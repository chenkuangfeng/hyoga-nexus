import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { computed } from 'vue'

// Exercise the actual sidebar grouping without mounting the settings panels.
const source = readFileSync(new URL('./Settings.vue', import.meta.url), 'utf8')
const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)![1]!
const ast = ts.createSourceFile('Settings.ts', script, ts.ScriptTarget.Latest, true)
const grouping = ast.statements.find((statement) =>
  ts.isVariableStatement(statement) && statement.declarationList.declarations.some(
    (declaration) => ts.isIdentifier(declaration.name) && declaration.name.text === 'navGroups',
  ),
)
assert.ok(grouping, 'Settings must define sidebar groups')
const compiled = ts.transpileModule(grouping.getText(ast), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText

test('MCP 连接位于账户设置，取消集成分组', () => {
  const groups = runInNewContext(`${compiled}\nnavGroups.value`, {
    computed, navItems: { value: ['general', 'mcp-endpoints', 'integration-im', 'integration-api'].map(key => ({ key })) }, t: (key: string) => key,
  }) as Array<{ key: string; items: Array<{ key: string }> }>
  assert.deepEqual(Array.from(groups.find(group => group.key === 'account')?.items || [], item => item.key), ['general', 'mcp-endpoints'])
  assert.equal(groups.some(group => group.key === 'integrations'), false)
})

// Keep navigation tests tied to the real close handler, without mounting
// settings panels that require backend services.
const closeHandler = ast.statements.find((statement) =>
  ts.isVariableStatement(statement) && statement.declarationList.declarations.some(
    (declaration) => ts.isIdentifier(declaration.name) && declaration.name.text === 'handleClose',
  ),
)
assert.ok(closeHandler, 'Settings must define a close handler')
const compiledClose = ts.transpileModule(closeHandler.getText(ast), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText

function closeSettings(back: unknown, section = 'members', path = '/platform/settings'): string[] {
  const actions: string[] = []
  class FocusedElement {
    blur() { actions.push('blur') }
  }
  runInNewContext(`${compiledClose}\nhandleClose()`, {
    document: { activeElement: new FocusedElement() },
    HTMLElement: FocusedElement,
    route: { path, query: { section } },
    uiStore: { closeSettings: () => actions.push('close') },
    router: {
      options: { history: { state: { back } } },
      push: (target: string) => actions.push(`push:${target}`),
      back: () => actions.push('back'),
    },
  })
  return actions
}

test('closing a directly opened settings route stays in the application', () => {
  for (const back of [null, undefined, '', 'https://example.com/', '//example.com/', '/login']) {
    assert.deepEqual(closeSettings(back), ['blur', 'close', 'push:/platform/knowledge-bases'])
  }
})

test('closing settings preserves a known in-app previous route', () => {
  for (const back of ['/platform/knowledge-bases', '/platform/chat/session-123']) {
    assert.deepEqual(closeSettings(back), ['blur', 'close', 'back'])
  }
})


test('closing an overlaid settings panel leaves the underlying route alone', () => {
  assert.deepEqual(closeSettings(null, 'general', '/platform/chat/session-123'), ['blur', 'close'])
})

test('已迁移的部门写页面不再进入工作台导航或模块依赖，旧书签保留迁移说明', () => {
  const groups = runInNewContext(`${compiled}\nnavGroups.value`, {
    computed, navItems: { value: ['tenant', 'members', 'org-structure'].map(key => ({ key })) }, t: (key: string) => key,
  }) as Array<{ items: Array<{ key: string }> }>
  assert.equal(groups.some(group => group.items.some(item => item.key === 'org-structure')), false)
  assert.equal(source.includes("import OrgStructure"), false)
  assert.equal(existsSync(new URL('./OrgStructure.vue', import.meta.url)), false)
})

test('旧企业治理页不再随工作台设置加载，账户资料保留本人企业操作', () => {
  assert.equal(source.includes('import TenantInfo'),false)
  assert.equal(existsSync(new URL('./TenantInfo.vue',import.meta.url)),false)
  const profile=readFileSync(new URL('./UserProfile.vue',import.meta.url),'utf8')
  assert.ok(profile.includes('CurrentEnterpriseMembership'))
})

test('工作台不再打包旧成员治理页或独占审批组件，普通入口不保留成员管理导航', () => {
 const groups=runInNewContext(`${compiled}\nnavGroups.value`,{computed,navItems:{value:['members','chathistory'].map(key=>({key}))},t:(key:string)=>key}) as Array<{items:Array<{key:string}>}>
 assert.equal(groups.some(group=>group.items.some(item=>item.key==='members')),false)
 assert.equal(existsSync(new URL('./TenantMembers.vue',import.meta.url)),false)
 assert.equal(existsSync(new URL('../../components/tenant/JoinApplicationsPanel.vue',import.meta.url)),false)
 assert.equal(source.includes('import TenantMembers'),false)
})

test('文件存储和向量库治理不进入员工设置导航，旧书签使用统一迁移说明', () => {
  const groups = runInNewContext(`${compiled}\nnavGroups.value`, {
    computed, navItems: { value: ['storage', 'vectorstore', 'general'].map(key => ({ key })) }, t: (key: string) => key,
  }) as Array<{ items: Array<{ key: string }> }>
  assert.equal(groups.some(group => group.items.some(item => ['storage', 'vectorstore'].includes(item.key))), false)
  for (const name of ['StorageBackendSettings', 'VectorStoreSettings']) {
    assert.equal(source.includes(`import ${name}`), false)
    assert.equal(existsSync(new URL(`./${name}.vue`, import.meta.url)), false)
  }
})

 test('旧治理书签仅展示迁移说明，不再要求原写页面的 admin 角色', async () => {
  const { isMigratedAdminSection } = await import('../../config/settingsRoute')
  const { SETTINGS_SECTION_MIN_ROLE } = await import('../../config/settingsAccess')
  const declaration = ast.statements.find(statement => ts.isVariableStatement(statement) && statement.declarationList.declarations.some(d => ts.isIdentifier(d.name) && d.name.text === 'canSeeSection'))
  assert.ok(declaration)
  const js = ts.transpileModule(declaration.getText(ast), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  const canSee = runInNewContext(`${js}\ncanSeeSection`, { isMigratedAdminSection, SETTINGS_SECTION_MIN_ROLE, authStore: { canAccessAllTenants: false, hasRole: () => false } })
  for (const section of ['storage', 'vectorstore', 'parser', 'members', 'org-structure']) assert.equal(canSee(section), true)
  assert.equal(canSee('sandbox'), false)
})
