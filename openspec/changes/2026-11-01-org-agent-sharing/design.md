# 设计：组织可见智能体

状态：第 1、2、3、4 项已确认，可以进入实施。

## 依赖

- 组织树、节点归属与空间绑定见 `2026-11-01-user-org-management`（已实施）。
- 分公司管理员的分层授权（`org_admins`，C+）尚未实施。第 7 项需求依赖它。在 C+ 确认并实施前，智能体分配只由平台管理员（`users.is_platform_admin`）操作。

## 数据模型

### `organization_agent_grants`：组织节点对智能体的分配

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `tenant_id` | 智能体所在空间，与 `agent_id` 组合外键确保一致 |
| `agent_id` | 智能体 |
| `unit_id` | 组织节点，覆盖该节点子树 |
| `permission` | 固定为 `view` 或 `run`，由数据库检查约束限定 |
| `created_by`、`created_at` | 分配人与时间 |

- 唯一约束：`(agent_id, unit_id)`。
- 撤销即删除行，审计记录保留撤销动作。
- 不保存 `edit`、`publish`、`manage`。权限上限在写入时校验，并由 `authz/catalog.py` 的 implication 规则约束。

### 与现有表的关系

- `tenant_agent_grants`（空间内角色对智能体的权限）不变。组织分配不写入这张表。
- `resource_grants`（跨空间资源共享）不变。
- `agent_resource_bindings` 记录智能体依赖的资源，包括 `source_tenant_id`。资源可能来自其他空间（经 `resource_grants` 共享）。见"资源与凭据"。

## 权限

- 分配与撤销：平台管理员。分公司管理员的分配范围待 C+ 确定。
- 组织侧读取与运行：调用者在某绑定节点的子树内（通过 `user_org_units` 与 `subtree_ids`），且该智能体对该节点有分配。`view` 允许看到智能体的名称、说明和可用性；`run` 允许创建会话并调用智能体。
- 调用者同时是空间成员时，以空间内的权限为准，组织分配只补充空间外的访问，不降低空间内的权限。
- 空间成员身份不因组织分配而改变。

## 资源与凭据

确认的规则：资源跟着智能体和空间走。具体约束：

- 智能体运行时使用的工具、知识库、模型配置，按智能体所在空间（以及资源所在的 `source_tenant_id`）解析。
- 组织成员的请求只传入用户输入和智能体标识，不传入资源或凭据。
- 组织成员的列表接口不返回资源 id、凭据、草稿内容、提示词全文（沿用空间内只读视图的裁剪规则）。
- 若智能体依赖其他空间（`source_tenant_id` 不是本空间）的资源，组织成员仍只能间接使用，且不能看到该资源所在空间的名称或内容。这一条需要在实施前用测试固定。

## 版本

- 组织侧运行的是智能体当前已发布版本（与空间内 `run` 一致）。草稿不对组织可见。
- 发布新版本后自动生效，不需要重新分配。

## 会话与记忆（已确认方案 A）

- 组织成员打开智能体时，切换到智能体所在的空间上下文。该空间的会话、运行记录与记忆都写入该空间：`tenant_id` 为智能体所在空间，`owner_user_id` 为组织成员。
- 现有会话与记忆的读取规则不变：只按 `owner_user_id` 过滤，空间的其他成员（包括 owner 与 admin）通过 API 看不到他人的会话。
- 组织成员的会话与记忆不因组织分配而对空间管理员开放。
- 实施时需要解决：会话相关的空间路由目前要求空间成员身份（`require_membership`）。组织成员切换到该空间时，这些路由要允许"对该智能体有组织分配且在子树内"的调用者进入，但只能访问自己的会话，并且只能运行被分配的智能体。
- 组织成员在该空间内的会话带有组织来源标记（例如 `source: organization`，记录分配的节点），便于空间管理员识别与审计。（待确认，见提案。）

## 聊天记录的读取规则（已确认，待实施确认）

现状：`sessions` 只有 `owner_user_id`，没有组织字段；`sessions.agent_version_id` 指向智能体版本，按智能体筛选需要经 `agent_versions.agent_id` 关联。`runs` 的可见性同样依赖 `owner_user_id`（`runs/repository.py`）。

规则：

- 普通用户：`owner_user_id = 当前用户`，可按智能体筛选。
- 空间管理员（`tenant_memberships` 的 role 为 owner 或 admin）：`tenant_id` 为其管理的空间，不限 owner。
- 平台管理员：不限空间与 owner，可按空间、智能体、组织筛选。

组织筛选的实现（待确认第 3 项，默认方案）：

- 在 `sessions` 上新增 `org_unit_id`（可空），会话创建时记录 owner 当时的主节点。筛选"组织"时，按节点子树匹配 `org_unit_id`。
- 备选：查询时用 `user_org_units` 实时计算。实现更简单，但人员调动后历史会话会改变归属，不利于审计。

范围与边界：

- 本次改聊天记录（`sessions`、`messages`、`runs` 的读取）和记忆（`memory_entries`、`memory_drafts` 的读取），规则相同。
- 会话检查点（`session_checkpoints`）随会话走，与其会话采用相同的读取规则。（实施时确认。）
- 空间管理员的读取范围只限其管理的空间，不包含其他空间。
- 组织成员在空间内的会话同样对空间管理员可见，与"组织访问标识"（提案待确认第 1 项）一起展示。

权限影响：空间 owner 与 admin 的会话读取范围扩大。这是现有权限规则的变化，需要更新 `authz` 中的会话读取判断与对应测试。

## 审计

- 组织侧（`org_audit_records`）：`org.agent_assigned`、`org.agent_unassigned`。
- 空间侧（`audit_records`）：`tenant.agent_org_shared`、`tenant.agent_org_unshared`。
- 组织侧的每次运行是否审计，待第 2 项一并确定。

## 测试计划

- 分配：权限上限拒绝 `edit`、`publish`、`manage`；停用节点拒绝新分配；重复分配被拒绝。
- 可见性：子树内人员可见且可运行；子树外人员返回 NotFound；撤销后立即不可见。
- 资源：组织成员的响应中不含资源 id、凭据、草稿内容；跨空间资源不泄露所在空间信息。
- 版本：发布新版本后组织侧运行新版本；草稿不可见。
- 与空间权限的叠加：空间内已有更高权限的成员，权限不降低。
- 迁移：SQLite 升级与回退。PostgreSQL 随路线图 2.9 验证。

## 参考项目

待实施前调研。WeKnora 的 AgentShare（agent_id、organization_id、source_tenant_id，权限固定为 viewer）和 receiver 视图（隐藏提示词与创建者）作为候选参考。按 AGENTS.md，编码前需要阅读源码并把结论写回本文件。
