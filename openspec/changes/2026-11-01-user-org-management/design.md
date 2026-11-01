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

### 平台管理员标识（方案 C）

`users.is_platform_admin`（布尔，默认 false）。由 `nexus_api.cli set-platform-admin --username` 设置或撤销，只针对密码账号。它不是租户角色，也不带范围：平台管理员可以管理全部组织树、节点人员、空间绑定和用户目录。

## 权限

- 组织树、节点人员、用户目录与绑定的管理接口要求 `users.is_platform_admin`。不新增 API 权限键或菜单键，`authz/catalog.py` 不变。
- 空间侧的组织视图只要求空间成员身份（`require_membership`）。空间成员可以看到绑定节点的子树和其中的人员。
- 解绑：平台管理员，或空间的 owner（`require_membership` 指定 `owner`）。
- 加入空间：需要 `members:manage`，且人员必须位于本空间的绑定子树内，否则返回 404。owner 不能通过此途径创建。

## 接口

组织（平台管理员）：

- `GET /api/v1/users?q=`：用户目录，按姓名或账号搜索，供选人。
- `POST /api/v1/orgs`、`GET /api/v1/orgs`：创建组织（根节点），列出组织。
- `GET /api/v1/orgs/{root_id}/tree`：整棵树，含节点状态与直接人数。
- `POST /api/v1/org-units`：在某节点下新增子节点，请求体 `parent_id`、`name`。
- `PATCH /api/v1/org-units/{unit_id}`：重命名、移动（`parent_id`）、启停（`status`）。
- `DELETE /api/v1/org-units/{unit_id}`：仅当无子节点、人员和绑定时允许。
- `PUT /api/v1/org-units/{unit_id}/members/{user_id}`：加入节点，请求体 `is_primary`。
- `DELETE /api/v1/org-units/{unit_id}/members/{user_id}`：移出节点。
- `GET /api/v1/org-units/{unit_id}/people`：子树内去重后的人员（实际路径；此前草案写作 `/members`）。
- `GET /api/v1/org-units/{unit_id}/bindings`：绑定到该节点的空间。

绑定：

- `PUT /api/v1/tenants/{tenant_id}/organization-bindings/{unit_id}`：平台管理员绑定。
- `DELETE /api/v1/tenants/{tenant_id}/organization-bindings/{unit_id}`：平台管理员或空间 owner 解绑。

空间（空间成员）：

- `GET /api/v1/tenants/{tenant_id}/organization`：绑定节点、子树结构和去重人员。
- `POST /api/v1/tenants/{tenant_id}/members/from-organization`：从绑定子树选人加入空间（方案 A）。

## 业务规则

- **移动节点**：新父节点不能是被移动节点本身或其子孙节点。检查通过递归查询完成，并在事务中锁定该组织树的根节点行（`SELECT ... FOR UPDATE`，SQLite 使用 `BEGIN IMMEDIATE`），避免并发移动造成环。
- **主节点**：设置新的主节点时，在同一事务中取消旧的主节点标记，并依赖部分唯一索引兜底。
- **停用节点**：停用的节点不能作为新归属或新绑定的目标。已有的归属和绑定保留，空间视图中标注"已停用"。停用不级联到子节点。
- **删除**：只允许删除无子节点、无归属、无空间绑定的节点。
- **绑定去重**：空间绑定集团根节点与某子公司节点时，人员列表按用户去重；同一用户在多个绑定节点下出现时，展示每个节点的归属，不重复计数。
- **空间成员的读取范围**：空间成员读取的只是绑定节点的子树，而不是整棵组织树的其他分支。

## 审计事件

组织侧（`org_audit_records`，以 `root_id` 标识组织树）：

- `org.created`、`org.unit_created`、`org.unit_updated`（含改名、移动、启停的变更内容）、`org.unit_deleted`
- `org.member_assigned`、`org.member_unassigned`
- `org.space_bound`、`org.space_unbound`

空间侧（`audit_records`）：

- `tenant.org_bound`、`tenant.org_unbound`
- `tenant.member_added`，并在元数据中记录 `source: organization`

`audit_records.tenant_id` 为非空，因此组织侧事件单独建表，不写入空间的审计表。

## 测试计划

- 树操作：创建子节点、移动（移到子孙节点下被拒绝）、名称唯一、删除前置条件、停用后不能作为目标。
- 归属：多节点归属、主节点唯一（服务层与数据库约束）、移除主节点的规则。
- 绑定：组织管理员绑定、重复绑定被拒绝、集团根节点与子公司节点同时绑定时人员去重、解绑权限（组织管理员与空间 owner）。
- 授权：非组织管理员访问组织接口返回 Forbidden；空间成员可以读取绑定子树的人员；非空间成员访问空间组织视图返回 NotFound；子树外的节点不可读取。
- 迁移：在 SQLite 上升级与回退，并验证部分唯一索引。PostgreSQL 验证随路线图 2.9 一并进行。

## 参考项目

本提案尚未做参考项目调研。按 AGENTS.md，编码前需要阅读路线图与架构文档中该模块标注的参考项目源码，比较候选实现，并把结论写入本文件。本设计目前以仓库已有的 `tenant_memberships` 与 `tenant_roles` 模式为依据。
