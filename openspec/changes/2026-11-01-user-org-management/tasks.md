# 实施任务

状态：已确认（第 2 项方案 A，第 3 项方案 C）。核心实施已完成，下列未完成项保留未勾选。

## 准备

- [ ] 阅读路线图与架构文档中该模块标注的参考项目源码，比较候选实现，结论写入 design.md。（未做，本次实施依据仓库已有的 `tenant_memberships` 与 `tenant_roles` 模式。）

## 数据与迁移

- [x] `org_units`、`user_org_units`（部分唯一索引：每人至多一个主节点）、`tenant_org_bindings`、`org_audit_records` 模型与迁移 `d1f5b8c2a9e4`。
- [x] `users.is_platform_admin`（方案 C，代替 `org_admins`）。
- [x] SQLite 升级、回退与模型一致性测试（`tests/test_platform_migrations.py`）。
- [ ] PostgreSQL 上的迁移与部分唯一索引验证，随路线图 2.9。

## 服务层

- [x] 组织树：创建根节点、新增子节点、重命名、移动（子孙节点检测、同树限制、树级锁）、停用、删除前置检查。
- [x] 人员归属：加入、移出、设为主节点（同一事务内切换），移出主节点前需先指定另一主节点。
- [x] 绑定：平台管理员绑定，同一空间与节点只能绑定一次；解绑由平台管理员或空间 owner 执行。
- [x] 子树人员查询（递归 CTE，按用户去重）。
- [x] 从绑定子树选人加入空间（需要 `members:manage`，owner 不可经此途径创建）。
- [x] 审计：组织侧写入 `org_audit_records`，空间侧写入 `audit_records`。

## 权限与接口

- [x] 平台管理员校验；不新增 API 权限键或菜单键。
- [x] 组织管理、空间组织视图、加入空间接口（`apps/api/src/nexus_api/http/orgs.py`）。
- [x] `GET /api/v1/users` 用户目录；`/auth/me` 返回 `is_platform_admin`。
- [x] 运维命令 `nexus_api.cli set-platform-admin`（授予或撤销）。

## 前端

- [x] 组织与人员页面（平台管理员）：组织列表与新建、树的增删改移与启停、节点人员（设为主节点、移出）、选人加入、绑定与解绑空间。
- [x] 空间组织页面：绑定节点与子树、去重人员、勾选后选择角色加入空间。
- [x] 导航：“组织与人员”仅对平台管理员显示。
- [x] 浏览器验收：`tests/web/organization.mjs`，并入 `test:browser`。

## 测试

- [x] `tests/test_user_organization.py`：树规则（深度不限、环检测、名称唯一）、主节点唯一、删除前置条件、绑定与子树去重、选人加入范围、解绑权限、停用节点、HTTP 层授权与路由、用户目录、节点绑定列表。
- [x] 后端全量测试通过（469 passed，1 skipped）。
- [x] 前端 `npm run build`（类型检查与生产构建）通过；既有四个浏览器用例与新增用例全部通过。

## 文档

- [x] `docs/architecture.md` 2.11 增加组织与空间绑定的说明。
- [x] `docs/roadmap.md` 新增 3.22。
- [x] `packages/platform/docs/requirements.md` 与 `design.md` 增加组织与人员章节。
- [x] OpenSpec proposal、design 与本文件按实施结果同步。

## 归档

- [ ] PostgreSQL 验证完成后，按 OpenSpec 工作流同步规格并归档。未完成的任务不标记完成。
