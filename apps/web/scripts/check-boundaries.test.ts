import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { checkBoundaries, forbiddenImport } from './check-boundaries.ts'

const root = fileURLToPath(new URL('..', import.meta.url))
test('三个项目遵守单向依赖边界', () => {
  assert.deepEqual(checkBoundaries(root), [])
})
test('别名与相对路径不能绕过边界', () => {
  assert.equal(forbiddenImport(root, 'core', `${root}/core/src/a.ts`, '@nexus-web/admin/router'), true)
  assert.equal(forbiddenImport(root, 'core', `${root}/core/src/a.ts`, '../../workspace/src/main'), true)
  assert.equal(forbiddenImport(root, 'workspace', `${root}/workspace/src/a.ts`, '../../admin/src/main'), true)
  assert.equal(forbiddenImport(root, 'admin', `${root}/admin/src/a.ts`, '@nexus-web/core/stores/auth'), false)
})
