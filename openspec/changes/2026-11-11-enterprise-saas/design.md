# 设计

本文件先写 E0、E1 的设计，以及 E2–E5 的要点。各阶段开始前补齐接口与表结构，并经用户确认。

## 1. 分层与原则

```text
平台运营方（is_platform_admin）
  └─ 企业（tenants.kind = 'enterprise'）── enterprise_policies、tenant_wecom_apps、企业上限
       ├─ 组织树（org_units / user_org_units，source = manual | wecom）
       ├─ 成员（tenant_memberships，source 增加 wecom）与角色（含 security_admin、auditor）
       └─ 智能体、知识库、技能、模型、会话、产物……
个人空间（tenants.kind = 'personal'）── 不属于任何企业，不受企业策略约束
共享空间 ── 跨租户协作，受各企业的 external_sharing 约束
```

- **只收紧**：平台守卫 ⊇ 企业策略 ⊇ 空间角色与资源授权。企业策略不能放宽平台已有的检查。
- **执行时复核**：策略、组织关系、成员状态、企业状态在每次请求和每次工具调用时重新查询，不进入 Run 快照。
- **按企业隔离**：新表都带 `tenant_id`，并用复合外键保证引用不跨企业（沿用 `org_units` 的做法）。

## 2. E0 知识库维护开放给智能体管理员

`packages/platform/src/nexus_platform/knowledge/access.py`：

```python
def can_maintain_content(db, kb, user_id) -> bool:
    """文档级维护：can_write 成立，或者调用者管理着一个绑定了该库的本企业智能体。"""
```

- 判断条件：`kb.status == 'active'`；调用者是 `kb.tenant_id` 的有效成员；存在 `agent`，满足 `agent.tenant_id == kb.tenant_id`、`agent_permissions(...)` 含 `manage`、草稿绑定或当前已发布版本的绑定中有 `kind = 'knowledge_base'` 且 `resource_id = kb.id`。
- 每次请求现查，不缓存。解除绑定或撤销 `manage` 后，下一次请求即失去权限。
- 接入点：文档上传、删除、重新解析，分块与问答的增删改走 `can_maintain_content`；库的设置、删除、共享、存储与解析器配置仍走 `can_write`。
- 审计：通过这条路径写入的操作，在审计 detail 中记录 `via_agent_id`。
- 前端：知识库列表的“可维护”标记由接口返回的 `can_maintain` 字段决定，不在前端推断。

## 3. E1 SaaS 企业底座

### 3.1 企业生命周期

- `tenants.status`：`pending`、`active`、`suspended`、`archived`。只有企业空间会出现 `pending` 和 `suspended`。
- `[platform].enterprise_signup = "open" | "review"`。`review` 模式下，注册的企业为 `pending`，注册人可以登录，但只能看到“等待开通”页面。
- 准入检查放在 `identity.service.require_membership` 一处，非 `active` 企业返回 403 `enterprise_inactive`。派发账本领取 Run 时同样检查：停用企业的队列项保持 `queued`，不领取。
- 平台接口 `/api/v1/platform/enterprises`：列表、详情、开通、停用、恢复、设定上限。只有平台管理员可用，写入 `platform_audit_records`（新表，与 `org_audit_records` 的形态一致）。
- 企业上限 `enterprise_limits`：`max_members`、`max_concurrent_sessions`、`monthly_tokens`（E4 使用），空值表示不限。

### 3.2 企业策略

`enterprise_policies(tenant_id PK, self_build_agents, self_build_org_unit_ids JSON, personal_models, external_sharing, retention_days, updated_by, updated_at)`。

- 读取接口对所有成员开放（前端据此隐藏入口），修改需要 `policy:manage`。
- 检查点：
  - 创建智能体：检查 `self_build_agents`，`org_units` 模式按调用者当前所在部门（含祖先）匹配；
  - 模型选择与 Run 准备：检查 `personal_models`；
  - 智能体与知识库共享到共享空间：检查 `external_sharing`，只要共享空间里有其他企业的成员租户就算外部；
  - 留存：E5。

### 3.3 个人空间边界

在以下入口加校验：源资源属于企业、目标属于个人空间时拒绝（403 `cross_space_forbidden`）。入口包括资源授权 `resource_grants`、智能体与知识库共享、会话分叉、技能复制、产物“另存到空间”（如有）。并补跨空间测试矩阵。

### 3.4 企业级管理角色

- `authz/catalog.py` 增加 `policy:manage`，并纳入 `GOVERNANCE_APIS`。
- 企业创建时写入两个内置角色：`security_admin`（`policy:manage`、`tools:manage`、`audit:read`）和 `auditor`（`audit:read`）。两者标记 `builtin = true`，不能删除、不能改名，但可以分配给成员。
- 审计正文：`auditor` 默认只看到元数据；查看对话正文另需 `audit:read_content`，并且每次查看本身也写入审计。

### 3.5 PostgreSQL 门禁

路线图 2.9 的全部项目，加上本提案的新表，在 PostgreSQL 上完成迁移往返和并发测试后，E1 才算验收。

## 4. E2 企业微信（要点）

- `tenant_wecom_apps` 的 `secret` 与 `encoding_aes_key` 用现有 Fernet 主密钥加密，不进事件与审计。
- 回调：每企业一个 URL `/api/v1/integrations/wecom/{tenant_id}/callback`，先验签解密，再分发到“通讯录变更”“消息”“卡片按钮”。
- `WeComDirectory` 协议扩展为：部门列表、部门成员详情、成员详情、发送应用消息、更新模板卡片。HTTP 实现放在 `connectors/wecom`，platform 只依赖协议。
- 同步顺序：部门 → 成员 → 主部门与上级 → 停用差集。上级保存在新表 `user_managers(tenant_id, user_id, manager_user_id, source)`。
- 自动开户：在 `auth/wecom.py` 的登录分支中，未绑定且 `(corp_id, userid)` 已同步的成员，创建 `users` 与 `user_identities`，不创建本地密码（`local_credentials` 为空，只能经企微登录，或由本人后来设置密码）。
- 消息渠道：沿用路线图 9.1 与 2.14 的约定（`ChannelIdentity`、`ChannelSessionBinding`、去重、回复长度、只在明确拒绝时重试）。

## 5. E3 组织驱动授权与审批（要点）

- `tenant_agent_grants` 当前只有 `role_id` 作为接收方。新增 `agent_principal_grants(tenant_id, agent_id, principal_kind, principal_id, permission, include_descendants)`，其中 `principal_kind` 取 `org_unit` 或 `user`。`agent_permissions` 取原有角色授权与新授权的并集。资源授权同理。
- 部门展开：用递归 CTE 求调用者所在部门的祖先集合，看授权的部门是否在其中（`include_descendants` 为真时）。每个请求内缓存一次。
- 审批人：`ActionApprovalRecord` 增加 `approver_kind` 与 `approver_user_ids`（发起时解析并冻结；决定时再校验审批人仍有效）。`resolve` 的权限由“Run 所有者”改为“在 `approver_user_ids` 中”。
- 超时：由 worker 的定时扫描处理，按拒绝结束，事件为 `approval.resolved`（`reason = 'timeout'`）。

## 6. E4 / E5（要点）

- E4：`usage_ledger(tenant_id, user_id, org_unit_id, agent_id, model_version_id, day, input, output, cache_read, cache_creation)` 从 `usage.updated` 事件累加。准入时检查企业、部门、个人三级的月度上限，超出返回 429 `quota_exhausted`；进行中的 Run 不中断。
- E5：worker 每天按 `retention_days` 清理会话、运行事件与产物，留存期内有法务保全标记的除外。审计按日导出为 JSONL，并写入哈希链字段。成员离职后，其企业内的记忆按企业策略删除或保留（默认删除）。
