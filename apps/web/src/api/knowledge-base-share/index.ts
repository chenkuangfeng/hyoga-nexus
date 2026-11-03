/**
 * 知识库共享到共享空间的客户端框架（`knowledge_base_shares`）。
 *
 * 当前状态：仅定义类型与接口签名，后端路由尚未实现，所有调用都会抛出
 * {@link KnowledgeBaseShareNotImplementedError}，避免请求落到不存在的接口上。
 * 实现时按 `api/agent-share` 的模式替换函数体即可，UI 层已可依赖这些签名。
 *
 * 计划的后端路由（与智能体共享保持同构，待第 1 阶段知识库模块接入后实现）：
 * - GET    /api/v1/tenants/:id/knowledge-bases/:kb_id/shares
 * - POST   /api/v1/tenants/:id/knowledge-bases/:kb_id/shares
 * - DELETE /api/v1/tenants/:id/knowledge-bases/:kb_id/shares/:shared_space_id
 * - GET    /api/v1/tenants/:id/shared-knowledge-bases
 *
 * 依赖：知识库模块（`docs/roadmap.md` 第 6 步检索相关内容）尚未接入，见
 * `openspec/changes/2026-11-03-enterprise-personal-spaces/tasks.md` 的“知识库共享”。
 */

/** 知识库共享给共享空间的级别：viewer（检索）、editor（+编辑文档）、admin（+管理共享）。 */
export type KnowledgeBaseShareLevel = 'viewer' | 'editor' | 'admin'

/** 企业侧：一个知识库已共享到的共享空间。 */
export interface KnowledgeBaseShare {
  id: string
  knowledge_base_id: string
  shared_space_id: string
  shared_space_name: string
  level: KnowledgeBaseShareLevel
  created_at: string
  owner_tenant_id: string
  owner_tenant_name: string
}

/** 共享空间成员侧：别的企业共享给我的知识库，`level` 为按自身角色取最小值后的有效级别。 */
export interface SharedKnowledgeBase {
  id: string
  name: string
  description: string
  owner_tenant_id: string
  owner_tenant_name: string
  level: KnowledgeBaseShareLevel
  permissions: string[]
}

/** 调用尚未实现的知识库共享接口时抛出。 */
export class KnowledgeBaseShareNotImplementedError extends Error {
  constructor(operation: string) {
    super(`knowledge base share "${operation}" is not implemented yet`)
    this.name = 'KnowledgeBaseShareNotImplementedError'
  }
}

/** 列出知识库已共享到的共享空间（仅所属企业的 owner、admin）。 */
export async function listKnowledgeBaseShares(
  _tenantId: string,
  _knowledgeBaseId: string,
): Promise<KnowledgeBaseShare[]> {
  throw new KnowledgeBaseShareNotImplementedError('listKnowledgeBaseShares')
}

/** 共享到共享空间，或修改已有共享的级别。 */
export async function shareKnowledgeBase(
  _tenantId: string,
  _knowledgeBaseId: string,
  _body: { shared_space_id: string; level: KnowledgeBaseShareLevel },
): Promise<void> {
  throw new KnowledgeBaseShareNotImplementedError('shareKnowledgeBase')
}

/** 取消知识库共享。 */
export async function unshareKnowledgeBase(
  _tenantId: string,
  _knowledgeBaseId: string,
  _sharedSpaceId: string,
): Promise<void> {
  throw new KnowledgeBaseShareNotImplementedError('unshareKnowledgeBase')
}

/** 当前空间通过共享空间可以检索的他人知识库。 */
export async function listSharedKnowledgeBases(_tenantId: string): Promise<SharedKnowledgeBase[]> {
  throw new KnowledgeBaseShareNotImplementedError('listSharedKnowledgeBases')
}
