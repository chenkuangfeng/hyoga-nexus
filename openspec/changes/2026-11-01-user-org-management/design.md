# 设计：用户组织管理

## 数据模型

### `org_units`：组织与部门（统一为树）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID，主键 | |
| `root_id` | UUID，外键指向本表 | 所属组织的根节点 id；根节点自身指向自己 |
| `parent_id` | UUID，可空，外键指向本表 | 根节点为空 |
| `kind` | 字符串，`organization` 或 `department` | 检查约束：根节点必须为 `organization`，子节点必须为 `department` |
| `name` | 字符串，1 到 160 字符 | 同一父节点下名称唯一 |
| `depth` | 整数 | 根节点为 0，用于深度上限检查 |
| `status` | `active` 或 `disabled` | 停用后不可用于新归属 |
| `created_at`、`updated_at` | 时间戳 | |

- 唯一约束：`(parent_id, name)`。SQLite 中 `parent_id` 为 NULL 时唯一约束不生效，根节点名称唯一由服务层检查，并用 `root_id` 加名称的唯一索引补足。
- 索引：`(root_id, parent_id)` 用于按层级读取。

### `user_org_units`：人员归属

| 字段 | 说明 |
| --- | --- |
| `user_id`、`unit_id` | 联合主键，`unit_id` 只能指向部门（`kind = department`） |
| `is_primary` | 布尔，每个用户最多一个为真 |
| `created_at` | |

- 部分唯一索引：`(user_id) WHERE is_primary`，SQLite 与 PostgreSQL 都支持。这样"只能有一个主部门"由数据库保证，而不只依赖服务层。
- 移除归属时若该行是主部门，服务层要求先指定另一个主部门，或该用户已无其他归属。

### `org_space_bindings`：组织与空间的关系

| 字段 | 说明 |
| --- | --- |
| `tenant_id` | 主键，一个空间最多一个有效绑定 |
| `org_id` | 指向 `org_units`（`kind = organization`） |
| `status` | `pending`（待对方确认）或 `active` |
| `requested_by`、`requested_side` | 发起方：`space` 或 `org` |
| `confirmed_by`、`confirmed_at` | 确认方与时间，`active` 时必填 |
| `created_at`、`updated_at` | |

- 一个组织可以对应多条绑定，即多个空间。
- 发起与确认必须来自两侧：发起方是空间 owner 时，确认方必须是组织的管理员，反之亦然。同一人不能既发起又确认。
- 解绑直接删除或置为 `revoked`，记录审计。

### `org_admins`：组织管理员

| 字段 | 说明 |
| --- | --- |
| `root_id`、`user_id` | 联合主键 |
| `role` | `owner` 或 `admin`，与空间的角色命名保持一致 |

组织创建者自动成为 `owner`。`owner` 可以指定或移除其他组织管理员，`admin` 可以管理组织树和人员归属，但不能管理组织管理员本身。

## 权限

- 新增 API 权限 `orgs:manage`，加入 `authz/catalog.py` 的 `API_PERMISSIONS`，并新增菜单 `orgs`。
- 组织管理接口的判断顺序：先检查调用者是否为该组织的 `org_admins` 成员，再检查 `orgs:manage`。组织权限与空间权限分开，不复用 `tenant_roles`（因为组织和空间是不同的边界）。
- 空间侧的组织信息接口只要求空间成员身份（`require_membership`），返回内容按第 6 节第 4 项裁剪。
- 空间 owner 确认绑定时，要求的是空间的 owner 角色（`ADMIN_ROLES` 中的 owner），而不是任意 admin。

## 接口草案

组织（需要组织管理员）：

- `POST /api/v1/orgs`：创建组织（同时创建根节点）。
- `GET /api/v1/orgs`：列出调用者管理的组织。
- `GET /api/v1/orgs/{root_id}/tree`：返回组织树，含节点的人数与停用状态。
- `POST /api/v1/orgs/{root_id}/units`：在某节点下新建部门。
- `PATCH /api/v1/org-units/{unit_id}`：重命名、移动（检查环与深度）、启停。
- `DELETE /api/v1/org-units/{unit_id}`：仅当节点无子节点、无人员归属时允许。
- `PUT /api/v1/org-units/{unit_id}/members/{user_id}`：加入部门，`is_primary` 作为请求体字段。
- `DELETE /api/v1/org-units/{unit_id}/members/{user_id}`：移出部门。
- `GET /api/v1/orgs/{root_id}/members`：组织人员列表（组织管理员）。

绑定：

- `POST /api/v1/tenants/{tenant_id}/organization-bindings`：空间或组织一侧发起，状态为 `pending`。
- `POST /api/v1/tenants/{tenant_id}/organization-bindings/confirm`：另一侧确认，状态变为 `active`。
- `DELETE /api/v1/tenants/{tenant_id}/organization-binding`：解绑。

空间视图：

- `GET /api/v1/tenants/{tenant_id}/organization`：返回绑定的组织名称、部门树、绑定状态。调用者若为组织管理员，额外返回组织人员（只读）。

## 业务规则

- **移动节点**：新父节点不能是被移动节点本身或其子孙节点；移动后，子树内所有节点的 `depth` 需要重算，并检查最大深度。在一个事务中完成，并锁定整棵树（`SELECT ... FOR UPDATE` 或同等的行锁），避免并发移动造成环。
- **主部门**：设置新的主部门时，在同一事务中取消旧的主部门标记，依赖部分唯一索引兜底。
- **停用节点**：停用的节点不能作为新归属的目标，已有归属保留。停用不级联到子节点，但子节点的可用性由其自身状态决定。
- **删除**：只允许删除无子节点、无归属的节点。
- **绑定确认**：确认时检查 `pending` 记录仍然存在且未过期（建议 7 天），同一空间只能有一个 `pending` 或 `active` 绑定。

## 审计事件

- `org.created`、`org.unit_created`、`org.unit_updated`、`org.unit_moved`、`org.unit_deleted`
- `org.member_assigned`、`org.member_unassigned`、`org.primary_changed`
- `org.admin_changed`
- `org.binding_requested`、`org.binding_confirmed`、`org.binding_revoked`

`audit_records.tenant_id` 目前为非空，而组织事件可能发生在没有绑定任何空间的组织上。推荐新增独立的 `org_audit_records` 表（字段与 `audit_records` 相同，但以 `root_id` 代替 `tenant_id`），不改动现有审计表。绑定与解绑事件同时写入两张表：组织表记录组织侧，空间的 `audit_records` 记录空间侧。

## 测试计划

- 树操作：创建、移动（包括移到子孙节点下被拒绝）、深度上限、删除前置条件、名称唯一。
- 归属：多部门归属、主部门唯一（服务层与数据库约束）、移除主部门的规则。
- 绑定：双方确认、同一人不能自我确认、重复绑定被拒绝、待确认超时。
- 授权：非组织管理员访问组织接口返回 Forbidden；空间 member 只看到组织名称与部门树，看不到人员列表；跨空间访问返回 NotFound。
- 迁移：在 SQLite 上升级与回退，并验证部分唯一索引。PostgreSQL 验证随路线图 2.9 一并进行。

## 与参考项目的对比

本提案尚未做参考项目调研。按 AGENTS.md，编码前需要阅读路线图与架构文档中该模块标注的参考项目源码，比较候选实现，并把结论写入本文件。本设计目前以仓库已有的 `tenant_memberships` 与 `tenant_roles` 模式为依据。
