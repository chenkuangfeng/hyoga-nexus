import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fixture } from '../test-utils/vueFixture'
const source = readFileSync(new URL('./enterprise-parsers.ts', import.meta.url), 'utf8')
test('完整替换保留密钥与扩展，显式清除密钥并保留 false，默认值删除', t => {
  const api = fixture(t).evaluate(source, { '../utils/request': {} })
  const snapshot = { mineru_api_key: '******', mineru_endpoint: 'old', mineru_enable_table: true, extension: 'retained', docreader_addr: 'legacy:50051', mineru_tier: 'legacy' }
  const result = api.parserConfigPayload(snapshot, { mineru_api_key: '', mineru_endpoint: ' new ', mineru_enable_table: false }, [])
  assert.deepEqual(JSON.parse(JSON.stringify(result)), { ...snapshot, mineru_endpoint: 'new', mineru_enable_table: false })
  assert.equal(api.parserConfigPayload(snapshot, {}, ['mineru_api_key']).mineru_api_key, undefined)
  assert.equal(api.parserConfigPayload(snapshot, {}, []).mineru_enable_table, undefined)
  assert.equal(api.parserConfigPayload(snapshot, { mineru_api_key: ' new-secret ' }, []).mineru_api_key, 'new-secret')
})
test('拒绝密钥明文和错误字段类型，目录状态不强制解释为连通结果', async t => {
  const api = fixture(t).evaluate(source, { '../utils/request': { get: async () => ({ data: [{ Name: 'mineru', Description: 'MinerU', FileTypes: ['pdf'], Available: false, UnavailableReason: 'missing endpoint' }] }) } })
  for (const data of [{ mineru_api_key: 'plaintext' }, { mineru_enable_table: 'false' }, { mineru_endpoint: 1 }]) assert.throws(() => api.parserConfigFromResponse({ data }), /parser_response_invalid/)
  assert.equal(api.parserConfigFromResponse({ data: { mineru_api_key: '******' } }).mineru_api_key, '******')
  assert.equal((await api.listEnterpriseParserEngines('a'))[0].configured, false)
})
test('读取和写入均限定编码后的当前企业管理接口', async t => {
  const paths: string[] = []
  const api = fixture(t).evaluate(source, { '../utils/request': { get: async (path: string) => { paths.push(path); return { data: {} } }, put: async (path: string) => { paths.push(path); return { data: {} } } } })
  await api.getEnterpriseParserConfig('a/b'); await api.saveEnterpriseParserConfig('a/b', {})
  assert.deepEqual(paths, Array(2).fill('/api/v1/tenants/a%2Fb/admin/knowledge/parser-engine-config'))
})
