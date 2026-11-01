# 设计：组织授予空间角色

状态：待确认提案（方案 2：组织角色独立计算，不写成员表）。

## 依赖

- 组织树、节点归属与空间绑定：`2026-11-01-user-org-management`（已实施）。绑定只由平台管理员完成。

## 数据模型

### `tenant_org_roles`：绑定节点授予的角色

| 字段 | 说明 |
| --- | --- |
| `tenant_id`、`unit_id` | 外键指向 `tenant_org_bindings(tenant_id, unit_id)`，级联删除 |
| `role_id` | 外键指向 `tenant_roles(id, tenant_id)`，必须是本空间的自定义角色 |
| `granted_by`、`granted_at` | 授予人与时间 |

- 主键：`(tenant_id, unit_id, role_id)`。一个绑定可以授予多个角色。
- 不允许授予 owner 或 admin：owner 和 admin 不是 `tenant_roles` 中的行，因此外键天然拒绝。
- 撤销即删除行。

### 不新增的表

- `organization_agent_grants`：不建。智能体访问全部经由角色的 `tenant_agent_grants`。
- 成员表：组织人员不写入。

### 已有表的变化

- `sessions` 增加 `org_unit_id`（可空）：会话创建时，若创建者通过组织获得访问，记录其绑定子树的节点（待确认第 4 项）。

## 权限计算

设 `U` 为用户，`T` 为空间。

1. **成员权限**：若存在 active 成员记录，沿用现有逻辑（owner、admin 为全部权限，member 为其个人角色的并集，`agents.created_by` 例外）。
2. **组织角色**：找出 `U` 所在的、绑定到 `T` 的节点中，子树包含 `U` 的那些绑定（`user_org_units` 与递归子树），取其 `tenant_org_roles` 中的角色。
3. 有效权限 = (1) ∪ (2)。
4. 若既无成员记录，又无组织角色，视为不存在，返回 NotFound。

实现要点：

- `effective_permissions` 与 `agent_permissions` 都要合并第 2 步的角色。角色的菜单、API 与智能体授权查询，使用同一组 `role_id` 集合，避免两处逻辑分叉。
- `require_membership`：只用于成员管理与 owner 操作，保持原样。读取类接口改为调用新的"成员或组织角色"判断。
- 组织角色持有人没有成员记录，因此不能执行依赖成员记录的操作（例如成员管理、移除成员）。

## 空间列表

`list_tenants` 返回的空间 = 成员记录所在的空间 ∪ 有组织角色的空间。组织来源的空间需要标记来源，供前端显示。

## 聊天记录与记忆读取规则

- 普通用户：`owner_user_id = 当前用户`。
- 空间管理员（成员记录为 owner 或 admin）：`tenant_id` 为其管理的空间，不限 owner。组织角色持有人不算空间管理员。
- 平台管理员：不限空间与 owner，可按空间、智能体、组织筛选。组织筛选按 `sessions.org_unit_id`（若第 4 项定为快照）或按 `user_org_units` 实时计算。

`runs/repository.py` 的可见性与会话使用同一规则。记忆与检查点同理。

## 审计

- 组织侧（`org_audit_records`）：`org.role_granted`、`org.role_revoked`。
- 空间侧（`audit_records`）：`tenant.org_role_granted`、`tenant.org_role_revoked`。

## 测试计划

- 授予：只接受本空间的自定义角色；owner 与 admin 不能通过组织授予；重复授予被拒绝。
- 权限合并：子树内人员获得绑定角色的智能体权限；子树外人员无权限；撤销后立即失效。
- 成员与组织叠加：成员记录的权限不因组织角色降低，组织角色只增加。
- 不写成员表：授予组织角色前后，成员表行数不变。
- 空间列表：组织来源的空间出现在列表中并带来源标记。
- 聊天记录：普通用户只见自己；空间 owner 与 admin 见本空间全部；组织角色持有人只见自己。
- 迁移：SQLite 升级与回退。PostgreSQL 随路线图 2.9 验证。

## 参考项目

待实施前调研。WeKnora 的 AgentShare 与 receiver 视图作为候选参考。按 AGENTS.md，编码前需要阅读源码并把结论写回本文件。
