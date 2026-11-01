# 设计：空间角色分配给组织人员

状态：待确认提案（角色由空间定义，按人员分配，不写成员表）。

## 依赖

- 组织树、节点归属与空间绑定：`2026-11-01-user-org-management`（已实施）。绑定只由平台管理员完成。

## 数据模型

### `tenant_org_user_roles`：空间内组织人员的角色

| 字段 | 说明 |
| --- | --- |
| `tenant_id`、`user_id`、`role_id` | 联合主键 |
| `assigned_by`、`assigned_at` | 分配人与时间 |

- 外键：`role_id` 与 `tenant_id` 组合引用 `tenant_roles(id, tenant_id)`，保证角色属于本空间。
- `user_id` 引用 `users`。不引用 `tenant_memberships`，因此没有成员记录的人也可以持有角色。
- 不允许 owner 或 admin：它们不是 `tenant_roles` 中的行，外键天然拒绝。
- 分配时校验：该用户必须在本空间某个绑定节点的子树内（递归子树 + `user_org_units`），否则返回 404。
- 访问时再次校验：角色只在用户仍处于绑定子树时生效。不一致的记录不删除，保留给重新回到子树的情况。

### 不新增的表

- `tenant_org_roles`（节点级角色）：不建。角色按人分配。
- `organization_agent_grants`：不建。智能体访问全部经由角色的 `tenant_agent_grants`。
- 成员表：组织人员不写入。

### 已有表的变化

- `sessions` 增加 `org_unit_id`（可空）：会话创建时，若创建者通过组织获得访问，记录其所在绑定子树的节点（待确认第 5 项）。

## 权限计算

设 `U` 为用户，`T` 为空间。

1. **成员权限**：若存在 active 成员记录，沿用现有逻辑（owner、admin 为全部权限，member 为其个人角色的并集，`agents.created_by` 例外）。
2. **组织人员角色**：取 `tenant_org_user_roles` 中 `(T, U)` 的角色，并且 `U` 仍在 `T` 的某个绑定子树内。
3. 有效权限 = (1) ∪ (2)。
4. 若既无成员记录，又无有效的组织人员角色，视为不存在，返回 NotFound。

实现要点：

- `effective_permissions` 与 `agent_permissions` 都要合并第 2 步的角色。角色的菜单、API 与智能体授权查询使用同一组 `role_id` 集合。
- `require_membership`：只用于成员管理与 owner 操作，保持原样。读取类接口改为调用"成员或有效组织人员角色"的判断。
- 没有成员记录的人不能执行依赖成员记录的操作（例如成员管理、移除成员）。

## 空间列表

`list_tenants` 返回的空间 = 成员记录所在的空间 ∪ 有效组织人员角色所在的空间。组织来源的空间需要标记来源，供前端显示。

## 聊天记录与记忆读取规则

- 普通用户：`owner_user_id = 当前用户`。
- 空间管理员（成员记录为 owner 或 admin）：`tenant_id` 为其管理的空间，不限 owner。没有成员记录的组织人员不算空间管理员。
- 平台管理员：不限空间与 owner，可按空间、智能体、组织筛选。组织筛选按 `sessions.org_unit_id`（若第 5 项定为快照）或按 `user_org_units` 实时计算。

`runs/repository.py` 的可见性与会话使用同一规则。记忆与检查点同理。

## 审计

- 组织侧（`org_audit_records`）：`org.member_role_granted`、`org.member_role_revoked`。
- 空间侧（`audit_records`）：`tenant.org_member_role_granted`、`tenant.org_member_role_revoked`。

## 测试计划

- 分配：只接受本空间的自定义角色；owner 与 admin 被拒绝；重复分配被拒绝；子树外的人员返回 404。
- 权限合并：子树内被分配者获得角色的智能体权限；撤销后立即失效。
- 失效与恢复：人员调出子树后角色不生效；调回子树后恢复；解绑后不生效。
- 成员与组织叠加：成员记录的权限不因组织角色降低，组织角色只增加。
- 不写成员表：分配前后成员表行数不变。
- 空间列表：组织来源的空间出现在列表中并带来源标记。
- 聊天记录：普通用户只见自己；空间 owner 与 admin 见本空间全部；没有成员记录的组织人员只见自己。
- 迁移：SQLite 升级与回退。PostgreSQL 随路线图 2.9 验证。

## 参考项目

待实施前调研。WeKnora 的 AgentShare 与 receiver 视图作为候选参考。按 AGENTS.md，编码前需要阅读源码并把结论写回本文件。
