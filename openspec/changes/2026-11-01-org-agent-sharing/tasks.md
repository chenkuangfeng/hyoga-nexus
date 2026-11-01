# 实施任务

状态：方案 X 已确认并实施核心部分。下列未勾选项是本次未完成的部分，见 design.md 的"未实施的部分"。

## 准备

- [x] 确认提案（方案 X：组织分配角色时写入成员表，来源标记为 `organization`）。
- [ ] 阅读 WeKnora 的 AgentShare 与 receiver 视图源码，比较候选实现，结论写入 design.md。（未做，本次按仓库现有模式实现。）

## 数据与迁移

- [x] `tenant_memberships.source` 与检查约束；迁移 `a6c3e9f2b1d8`。
- [x] `sessions.org_unit_id`（可空，外键置空）。
- [x] SQLite 升级与回退（`tests/test_platform_migrations.py`）。
- [ ] PostgreSQL 验证随路线图 2.9。

## 权限与有效性

- [x] `orgs/access.py`：`membership_is_active`、`is_space_manager`、`organization_unit_for`、`bound_unit_ids`。
- [x] `require_membership`、`effective_permissions`、`agent_permissions`、`visible_agent_ids`、`list_tenants` 统一使用有效性判断。
- [x] 组织来源成员调出或解绑后失效，重新绑定后恢复。

## 服务与接口

- [x] 从绑定子树选人并分配角色（`from-organization` 接口，请求体 `role_ids`）。
- [x] 撤销最后一个角色时删除组织来源的成员记录。
- [x] 会话创建时记录 `org_unit_id` 快照。
- [x] 会话列表与详情：owner 与 admin 看全部，其他人只看自己。
- [x] 运行详情：owner 与 admin 可见本空间全部运行。
- [ ] 记忆（`memory_entries`、`memory_drafts`、`session_checkpoints`）的空间管理员可见性。
- [ ] 平台管理员跨空间查看聊天记录，以及按智能体、组织、空间的筛选。
- [ ] 会话接口返回 `org_unit_id`。

## 前端

- [x] 空间组织页面改为多选角色后分配（`SpaceOrganizationView.vue`，`api/orgs.ts`）。
- [ ] 空间列表的组织来源标记。
- [ ] "组织访问"标识。
- [x] 浏览器验收用例更新（`tests/web/organization.mjs`），并通过；其余四个用例也通过。

## 测试

- [x] 分配角色后权限生效，解绑后失效、重新绑定后恢复（`tests/test_org_member_roles.py`）。
- [x] 撤销最后一个角色后组织来源成员记录被删除，手动成员保留。
- [x] owner 与 admin 看到全部会话，成员只看到自己的（同上文件）。
- [x] 组织接口的授权与路由（`tests/test_user_organization.py`）。
- [x] 后端全量测试：472 passed, 1 skipped。
- [x] 前端 `npm run build` 通过；浏览器用例 auth、conversation、model-settings、roles、organization 全部通过。

## 文档

- [x] OpenSpec proposal、design、tasks 与实施结果一致。
- [ ] `docs/architecture.md`、`docs/roadmap.md` 与 `packages/platform/docs/` 更新为方案 X。

## 归档

- [ ] 未完成项完成并验证后，按 OpenSpec 工作流同步规格并归档。
