import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { computed } from 'vue'

test('可复制的 MCP 基础地址使用网页 origin 并保留部署前缀', () => {
  const source = ts.transpileModule(readFileSync(new URL('./useApiBaseUrlDisplay.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  for (const [base, expected] of [['', 'https://example.com/api/v1'], ['/nexus/', 'https://example.com/nexus/api/v1']]) {
    const exports: any = {}
    runInNewContext(source, { exports, URL, window: { location: { origin: 'https://example.com' } }, require: (name: string) => name === 'vue' ? { computed } : { getApiBaseUrl: () => base } })
    assert.equal(exports.useApiBaseUrlDisplay().apiBaseUrlDisplay.value, expected)
  }
})
