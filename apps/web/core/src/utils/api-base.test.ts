import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import axios from 'axios'
import ts from 'typescript'

test('管理页面路径不成为 API 前缀，员工端及子路径部署保持原地址', () => {
  const source = readFileSync(new URL('./api-base.ts', import.meta.url), 'utf8')
  for (const [pageBase, expected] of [['/', '/api/v1/auth/login'], ['/enterprise/', '/api/v1/auth/login'], ['/app/weknora/', '/app/weknora/api/v1/auth/login'], ['/nexus/enterprise/', '/nexus/api/v1/auth/login']]) {
    const exports: { getApiBaseUrl?: () => string } = {}
    runInNewContext(ts.transpileModule(source.replaceAll('import.meta.env.BASE_URL', JSON.stringify(pageBase)), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports })
    const request = axios.create({ baseURL: exports.getApiBaseUrl!() })
    assert.equal(request.getUri({ url: '/api/v1/auth/login' }), expected)
  }
})
