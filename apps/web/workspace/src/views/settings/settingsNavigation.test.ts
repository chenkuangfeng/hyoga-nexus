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
