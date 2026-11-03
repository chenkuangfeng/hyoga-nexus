import { del, get, post } from '@/utils/request'

/** 智能体共享给共享空间的级别：viewer（查看、运行）、editor（+编辑）、admin（+发布、管理）。 */
export type AgentShareLevel = 'viewer' | 'editor' | 'admin'

/** 企业侧：一个智能体已共享到的共享空间。 */
export interface AgentShare {
  id: string
  agent_id: string
  shared_space_id: string
  shared_space_name: string
  level: AgentShareLevel
  created_at: string
  owner_tenant_id: string
  owner_tenant_name: string
}

/** 共享空间成员侧：别的企业共享给我的智能体，`level` 为有效级别（已按自身角色取最小值）。 */
export interface SharedAgent {
  id: string
  name: string
  description: string
  status: string
  owner_tenant_id: string
  owner_tenant_name: string
  level: AgentShareLevel
  permissions: string[]
}

/**
 * 列出智能体已共享到的共享空间（仅所属企业的 owner、admin）。
 * Backend: GET /api/v1/tenants/:id/agents/:agent_id/shares
 */
export async function listAgentShares(tenantId: string, agentId: string): Promise<AgentShare[]> {
  return (await get(`/api/v1/tenants/${tenantId}/agents/${agentId}/shares`)) as unknown as AgentShare[]
}

/**
 * 共享到共享空间，或修改已有共享的级别。Backend: POST /api/v1/tenants/:id/agents/:agent_id/shares
 */
export async function shareAgent(
  tenantId: string,
  agentId: string,
  body: { shared_space_id: string; level: AgentShareLevel },
): Promise<void> {
  await post(`/api/v1/tenants/${tenantId}/agents/${agentId}/shares`, body)
}

/** 取消共享。Backend: DELETE /api/v1/tenants/:id/agents/:agent_id/shares/:shared_space_id */
export async function unshareAgent(tenantId: string, agentId: string, sharedSpaceId: string): Promise<void> {
  await del(`/api/v1/tenants/${tenantId}/agents/${agentId}/shares/${sharedSpaceId}`)
}

/**
 * 当前空间通过共享空间可以读取的他人智能体。Backend: GET /api/v1/tenants/:id/shared-agents
 */
export async function listSharedAgents(tenantId: string): Promise<SharedAgent[]> {
  return (await get(`/api/v1/tenants/${tenantId}/shared-agents`)) as unknown as SharedAgent[]
}
