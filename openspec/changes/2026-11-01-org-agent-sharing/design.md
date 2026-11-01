# 设计：空间角色分配给组织人员（方案 X）

状态：已实施核心部分（成员来源、有效性判断、角色分配、会话与运行的可见性）。未完成的部分见 tasks.md。

## 依赖

- 组织树、节点归属与空间绑定：`2026-11-01-user-org-management`（已实施）。绑定只由平台管理员完成。

## 数据模型

### `tenant_memberships.source`（新增）

- 取值 `manual`（个人显式加入，默认）或 `organization`（因组织分配角色而创建）。
- 检查约束 `ck_membership_source`。迁移 `a6c3e9f2b1d8` 给既有行设为 `manual`。
- 成员字段 `role` 对组织来源的成员固定为 `member`。owner 与 admin 不能经组织获得。

### `sessions.org_unit_id`（新增，可空）

- 会话创建时，若创建者的成员记录来源为 `organization`，记录其所在绑定子树内的节点（优先主节点）。外键 `fk_sessions_org_unit_id`，删除节点时置空。
- 手动成员创建的会话为 null。用于审计与平台管理员按组织筛选。

### 不新增的表

- `tenant_org_roles`、`tenant_org_user_roles`、`organization_agent_grants`：均不建。角色分配沿用 `tenant_user_roles`，智能体访问沿用 `tenant_agent_grants`。

## 有效性规则（`orgs/access.py`）

成员记录是否生效，统一由 `membership_is_active` 判断：

- 状态不是 active：无效。
- 来源为 `manual`：有效。
- 来源为 `organization`：仅当该用户仍位于本空间某个绑定子树内时有效。

这一判断被以下位置调用：`identity.require_membership`、`authz.effective_permissions`、`agents.access.agent_permissions` 与 `visible_agent_ids`、`tenants.list_tenants`。因此解绑或调出子树后，空间列表不再显示，访问返回 NotFound，但记录保留；重新绑定后自动恢复。

## 角色分配

- 入口：`POST /api/v1/tenants/{tenant_id}/members/from-organization`，请求体 `user_ids` 与 `role_ids`（至少一个，均不能为空）。需要 `members:manage`。
- 每个人员必须位于本空间绑定子树内，否则 404。角色必须是本空间的自定义角色，否则 404。
- 没有成员记录：创建 `member`、来源 `organization` 的记录。已撤销的记录：恢复为 `organization` 来源。已有有效记录：保留原来源，不改动。
- 为每个所选角色写入 `tenant_user_roles` 中缺失的行，因此重复调用安全。
- 返回 `added`（新加入成员的人）与 `skipped`（已是成员的人）。
- 撤销：`unassign_role` 删除角色行；若该人没有任何剩余角色，且成员来源为 `organization`，同时删除成员记录。手动成员不会被删除。

## 会话与运行的可见性

- 平台管理员：`GET /api/v1/admin/sessions`，可按 `tenant_id`、`agent_id`、`org_unit_id` 筛选（组织节点含子树）。非平台管理员返回 403。
- 记忆（`memory_entries`、`memory_drafts`、`session_checkpoints`）只对本人可见，空间管理员和平台管理员均不例外。

- 普通成员（包括组织来源）：只能看到 `owner_user_id` 为自己的会话、运行与消息。
- 空间管理员（成员记录为 owner 或 admin，且有效）：可以看到本空间全部会话与运行。`is_space_manager` 判断。
- 组织来源的成员始终是 `member`，因此不是空间管理员。
- 会话创建时若来自组织，`sessions.org_unit_id` 写入快照。

实现位置：`sessions/service.py`（列表与详情）、`runs/repository.py`（`visible`）。

## 审计

- 空间侧：`tenant.member_added`，元数据含 `source: organization`、`role_ids` 与 `joined`。
- 撤销角色沿用 `tenant.role_unassigned`。

## 未实施的部分

- 前端"组织访问"标识与空间列表来源标记：待确认后实施。
- 平台管理员的会话列表页面（后端接口已完成）。
- 组织人员调出子树后，不删除记录，也不主动清理；目前只是失效。
