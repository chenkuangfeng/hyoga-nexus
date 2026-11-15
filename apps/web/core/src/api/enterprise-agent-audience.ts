/** 部门和成员获得企业智能体的 view/run 使用权；不替换角色 grant 或维护权限。 */
import { get, put } from '../utils/request'

export interface AgentAudienceItem { kind: 'user' | 'org_unit'; id: string; include_descendants: boolean }
export interface AgentAudience { items: AgentAudienceItem[] }
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('agent_audience_response_invalid'); return value as Record<string, unknown> }
function string(value: unknown): string { if (typeof value !== 'string' || !value.trim()) throw new Error('agent_audience_response_invalid'); return value }
export function agentAudienceFromResponse(value: unknown): AgentAudience {
  const items = object(value).items
  if (!Array.isArray(items) || items.length > 500) throw new Error('agent_audience_response_invalid')
  const parsed = items.map(value => {
    const row = object(value)
    if (row.kind !== 'user' && row.kind !== 'org_unit') throw new Error('agent_audience_response_invalid')
    if (typeof row.include_descendants !== 'boolean') throw new Error('agent_audience_response_invalid')
    const kind: AgentAudienceItem['kind'] = row.kind
    return { kind, id: string(row.id), include_descendants: row.include_descendants }
  })
  if (new Set(parsed.map(item => `${item.kind}:${item.id}`)).size !== parsed.length) throw new Error('agent_audience_response_invalid')
  return { items: parsed }
}
const path = (tenant: string, agent: string) => `/api/v1/tenants/${encodeURIComponent(tenant)}/agents/${encodeURIComponent(agent)}/audience`
export async function getAgentAudience(tenant: string, agent: string): Promise<AgentAudience> { return agentAudienceFromResponse(await get(path(tenant, agent))) }
/** 整体替换直接使用受众；服务端核实成员、部门、维护权限和绑定知识库覆盖范围。 */
export async function setAgentAudience(tenant: string, agent: string, items: AgentAudienceItem[]): Promise<AgentAudience> {
  if (!Array.isArray(items) || items.length > 500 || items.some(item => !item || !['user', 'org_unit'].includes(item.kind) || !item.id.trim() || typeof item.include_descendants !== 'boolean')
      || new Set(items.map(item => `${item.kind}:${item.id}`)).size !== items.length) throw new Error('agent_audience_response_invalid')
  const result = agentAudienceFromResponse(await put(path(tenant, agent), { items }))
  const expected = items.map(item => `${item.kind}:${item.id}:${item.include_descendants}`).sort(), received = result.items.map(item => `${item.kind}:${item.id}:${item.include_descendants}`).sort()
  if (expected.length !== received.length || expected.some((value, index) => value !== received[index])) throw new Error('agent_audience_response_invalid')
  return result
}
