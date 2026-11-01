# 设计：用户组织管理

## 数据模型

### `org_units`：组织树（集团、子公司、部门统一为节点）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID，主键 | |
| `root_id` | UUID，外键指向本表 | 所在组织树的根节点 id；根节点指向自己 |
| `parent_id` | UUID，可空，外键指向本表 | 根节点为空 |
| `name` | 字符串，1 到 160 字符 | 同一父节点下名称唯一 |
| `status` | `active` 或 `disabled` | 停用后不可用于新归属和新绑定 |
| `created_at`、`updated_at` | 时间戳 | |

- 节点的类型（集团、子公司、部门）由位置决定，不单独存储：根节点是集团，根节点的直接子节点通常是子公司，更深的节点是部门。平台不强制类型，层级不限。
- 唯一约束：`(parent_id, name)`。`parent_id` 为 NULL 的根节点，名称唯一由服务层检查。
- 索引：`(root_id, parent_id)` 用于按层级读取。
- 不保存 `depth`。层级不限，需要时用递归查询计算。

### `user_org_units`：人员归属

| 字段 | 说明 |
| --- | --- |
| `user_id`、`unit_id` | 联合主键，`unit_id` 指向任意有效节点 |
| `is_primary` | 布尔，每个用户最多一个为真 |
| `created_at` | |

- 部分唯一索引：`(user_id) WHERE is_primary`，SQLite 与 PostgreSQL 都支持，由数据库保证"只能有一个主节点"。
- 移除归属时若该行是主节点，服务层要求先指定另一个主节点，或该用户已无其他归属。
- 人员就是 `users`，不另建人员实体。

### `tenant_org_bindings`：空间与组织节点的绑定

| 字段 | 说明 |
| --- | --- |
| `tenant_id`、`unit_id` | 联合主键，同一空间不能重复绑定同一节点 |
| `created_by` | 绑定的组织管理员 |
| `created_at` | |

- 多对多：一个空间可以绑定多个节点（集团空间绑定集团根节点，或绑定若干子公司节点）；一个节点也可以被多个空间绑定。
- 绑定的是节点，覆盖该节点的整个子树。绑定集团根节点时，子树包括所有子公司和部门。
- 绑定和解绑由组织管理员完成，空间 owner 也可以解绑。

### `org_admins`：组织管理员（待定，见 proposal.md 第 6 节第 3 项）

| 字段 | 说明 |
| --- | --- |
| `unit_id`、`user_id` | 联合主键；`unit_id` 为管理范围的根节点，管理权限覆盖该节点的子树 |
| `role` | `owner` 或 `admin` |

推荐方案：管理范围限定在节点子树内，集团管理员管整棵树，子公司管理员只管本子公司。方案确定前，本表的结构只是草案。

## 权限

- 新增 API 权限 `orgs:manage`，加入 `authz/catalog.py` 的 `API_PERMISSIONS`，并新增菜单 `orgs`。
- 组织管理接口：调用者需要在目标节点的管理范围内（`org_admins`，含祖先节点的授权）并拥有 `orgs:manage`。
- 空间侧的组织信息接口：要求空间成员身份（`require_membership`）。空间成员可以看到绑定节点的子树（名称、结构、人员列表）。
- 绑定与解绑接口：组织侧要求对该节点有管理权限；空间侧解绑要求空间 `owner`（`ADMIN_ROLES` 中的 owner）。

## 接口草案

组织（组织管理员）：

- `POST /api/v1/orgs`：创建组织树（根节点）。
- `GET /api/v1/orgs`：列出调用者可管理的根节点。
- `GET /api/v1/orgs/{root_id}/tree`：返回整棵树，含节点状态与人数。
- `POST /api/v1/org-units`：在某节点下新建子节点，请求体含 `parent_id`、`name`。
- `PATCH /api/v1/org-units/{unit_id}`：重命名、移动（检查环）、启停。
- `DELETE /api/v1/org-units/{unit_id}`：仅当节点无子节点、无人员归属、无空间绑定时允许。
- `PUT /api/v1/org-units/{unit_id}/members/{user_id}`：加入节点，请求体含 `is_primary`。
- `DELETE /api/v1/org-units/{unit_id}/members/{user_id}`：移出节点。
- `GET /api/v1/org-units/{unit_id}/members`：子树内的人员列表（去重），标注所在节点与是否主节点。

绑定：

- `PUT /api/v1/tenants/{tenant_id}/organization-bindings/{unit_id}`：组织管理员绑定。
- `DELETE /api/v1/tenants/{tenant_id}/organization-bindings/{unit_id}`：组织管理员或空间 owner 解绑。

空间视图（空间成员）：

- `GET /api/v1/tenants/{tenant_id}/organization`：返回所有绑定节点，每个节点包含：名称、所在组织名称、子树结构、子树内去重后的人员列表（用户名、显示名、所在节点、是否主节点）。

## 业务规则

- **移动节点**：新父节点不能是被移动节点本身或其子孙节点。检查通过递归查询完成，并在事务中锁定该组织树的根节点行（`SELECT ... FOR UPDATE`，SQLite 使用 `BEGIN IMMEDIATE`），避免并发移动造成环。
- **主节点**：设置新的主节点时，在同一事务中取消旧的主节点标记，并依赖部分唯一索引兜底。
- **停用节点**：停用的节点不能作为新归属或新绑定的目标。已有的归属和绑定保留，空间视图中标注"已停用"。停用不级联到子节点。
- **删除**：只允许删除无子节点、无归属、无空间绑定的节点。
- **绑定去重**：空间绑定集团根节点与某子公司节点时，人员列表按用户去重；同一用户在多个绑定节点下出现时，展示每个节点的归属，不重复计数。
- **空间成员的读取范围**：空间成员读取的只是绑定节点的子树，而不是整棵组织树的其他分支。

## 审计事件

- `org.created`、`org.unit_created`、`org.unit_updated`、`org.unit_moved`、`org.unit_deleted`
- `org.member_assigned`、`org.member_unassigned`、`org.primary_changed`
- `org.admin_changed`（待定项确认后）
- `org.binding_created`、`org.binding_removed`

`audit_records.tenant_id` 目前为非空，而组织事件可能发生在没有绑定任何空间的组织上。推荐新增独立的 `org_audit_records` 表（字段与 `audit_records` 相同，但以 `root_id` 代替 `tenant_id`），不改动现有审计表。绑定与解绑事件同时写入两张表：组织表记录组织侧，空间的 `audit_records` 记录空间侧。

## 测试计划

- 树操作：创建子节点、移动（移到子孙节点下被拒绝）、名称唯一、删除前置条件、停用后不能作为目标。
- 归属：多节点归属、主节点唯一（服务层与数据库约束）、移除主节点的规则。
- 绑定：组织管理员绑定、重复绑定被拒绝、集团根节点与子公司节点同时绑定时人员去重、解绑权限（组织管理员与空间 owner）。
- 授权：非组织管理员访问组织接口返回 Forbidden；空间成员可以读取绑定子树的人员；非空间成员访问空间组织视图返回 NotFound；子树外的节点不可读取。
- 迁移：在 SQLite 上升级与回退，并验证部分唯一索引。PostgreSQL 验证随路线图 2.9 一并进行。

## 参考项目

本提案尚未做参考项目调研。按 AGENTS.md，编码前需要阅读路线图与架构文档中该模块标注的参考项目源码，比较候选实现，并把结论写入本文件。本设计目前以仓库已有的 `tenant_memberships` 与 `tenant_roles` 模式为依据。
