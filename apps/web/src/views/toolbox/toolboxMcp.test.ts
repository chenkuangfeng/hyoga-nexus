import assert from 'node:assert/strict'
import test from 'node:test'
import type { McpService, McpServiceTool } from '@/api/nexus-mcp'
import {
  configFromForm, enabledToolNames, entriesToRows, formFromService, rowsToEntries, serviceTarget,
  validateMcpForm,
} from './toolboxMcp'

const service = (over: Partial<McpService> = {}): McpService => ({
  id: 's1',
  tenant_id: 't1',
  name: 'GitHub',
  description: '',
  transport: 'streamable_http',
  config: { transport: 'streamable_http', timeout: 30, auth_type: 'none', url: 'https://example.com/mcp' },
  enabled: true,
  config_epoch: 'e1',
  created_by: 'u1',
  created_at: '2026-11-09T00:00:00Z',
  updated_at: '2026-11-09T00:00:00Z',
  ...over,
})

const tool = (over: Partial<McpServiceTool> = {}): McpServiceTool => ({
  tool_name: 'echo',
  description: '',
  enabled: true,
  read_only_hint: true,
  catalog_status: 'ready',
  catalog_error: null,
  explicit_risk: null,
  observed_risk: null,
  effective_risk: 'read',
  require_approval: false,
  pending_downgrade: false,
  ...over,
})

test('header and env rows keep credential references as references', () => {
  const rows = entriesToRows({
    Authorization: { $credential_ref: 'cred-1' },
    'X-Plain': 'literal',
  })
  assert.deepEqual(rows, [
    { key: 'Authorization', value: 'cred-1', reference: true },
    { key: 'X-Plain', value: 'literal', reference: false },
  ])
  assert.deepEqual(rowsToEntries(rows), {
    Authorization: { $credential_ref: 'cred-1' },
    'X-Plain': 'literal',
  })
})

test('blank rows are dropped instead of being sent as empty headers', () => {
  assert.deepEqual(rowsToEntries([
    { key: '  ', value: 'x', reference: false },
    { key: 'X-Empty', value: '  ', reference: false },
    { key: ' X-Trimmed ', value: ' v ', reference: false },
  ]), { 'X-Trimmed': 'v' })
})

test('a stored http service round-trips through the form without losing fields', () => {
  const stored = service({
    transport: 'sse',
    config: {
      transport: 'sse', timeout: 45, auth_type: 'oauth', url: 'https://example.com/sse',
      headers: { Authorization: { $credential_ref: 'cred-1' } }, sse_read_timeout: 120,
      oauth: { scopes: ['repo', 'read:user'], client_id: 'client-1', client_secret: 'stored-secret' },
    },
  })
  const form = formFromService(stored)
  assert.equal(form.transport, 'sse')
  assert.equal(form.timeout, 45)
  assert.equal(form.sseReadTimeout, 120)
  assert.equal(form.authType, 'oauth')
  assert.equal(form.oauthScopes, 'repo read:user')
  assert.equal(form.oauthClientId, 'client-1')
  assert.deepEqual(form.headers, [{ key: 'Authorization', value: 'cred-1', reference: true }])

  const config = configFromForm(form, stored)
  assert.equal(config.transport, 'sse')
  assert.equal(config.auth_type, 'oauth')
  assert.equal(config.sse_read_timeout, 120)
  assert.deepEqual(config.oauth?.scopes, ['repo', 'read:user'])
  assert.equal(config.oauth?.client_id, 'client-1')
  // The client secret is not editable in the dialog; saving must carry the stored one over.
  assert.equal(config.oauth?.client_secret, 'stored-secret')
})

test('a stdio form emits command, args and env and never an HTTP authorization mode', () => {
  const form = formFromService(null)
  form.transport = 'stdio'
  form.authType = 'oauth'
  form.command = ' npx '
  form.args = '-y\n\n@modelcontextprotocol/server-github\n'
  form.env = [{ key: 'GITHUB_TOKEN', value: 'cred-2', reference: true }]
  const config = configFromForm(form)
  assert.equal(config.transport, 'stdio')
  assert.equal(config.auth_type, 'none')
  assert.equal(config.command, 'npx')
  assert.deepEqual(config.args, ['-y', '@modelcontextprotocol/server-github'])
  assert.deepEqual(config.env, { GITHUB_TOKEN: { $credential_ref: 'cred-2' } })
  assert.equal(config.url, undefined)
})

test('validation names the first blocking field', () => {
  const form = formFromService(null)
  assert.equal(validateMcpForm(form), 'nameRequired')
  form.name = 'GitHub'
  assert.equal(validateMcpForm(form), 'urlRequired')
  form.url = 'ftp://example.com'
  assert.equal(validateMcpForm(form), 'urlRequired')
  form.url = 'https://example.com/mcp'
  assert.equal(validateMcpForm(form), null)
  form.transport = 'stdio'
  assert.equal(validateMcpForm(form), 'commandRequired')
  form.command = 'npx'
  assert.equal(validateMcpForm(form), null)
})

test('the row target and the enabled whitelist follow the service state', () => {
  assert.equal(serviceTarget(service()), 'https://example.com/mcp')
  assert.equal(serviceTarget(service({
    transport: 'stdio', config: { transport: 'stdio', command: 'npx', args: ['-y', 'server'] },
  })), 'npx -y server')
  assert.deepEqual(enabledToolNames([
    tool({ tool_name: 'a' }),
    tool({ tool_name: 'b', enabled: false }),
    tool({ tool_name: 'c', enabled: true }),
  ]), ['a', 'c'])
})
