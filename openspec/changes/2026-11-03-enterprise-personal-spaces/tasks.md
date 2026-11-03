# 实施任务

状态：已确认（2026-11-03），第 1 阶段实施中。确认结果见 `proposal.md`，对齐映射见 `design.md` 第 9 节。每组完成后与 WeKnora 对应页面逐项比对，结果记录在该组末尾。

## 0. 前端基础（`apps/web`）

按 2026-11-03 的决定，`apps/web` 整体替换为 WeKnora 前端的复制版本（删除原 Element Plus 界面），以下为复制后的处理结果。生产构建在本机因内存不足无法完成，以 CI 为准。

- [x] 依赖：复制 WeKnora 的 `package.json`（TDesign、pinia、vue-router、vue-i18n、axios），改用 pnpm，`pnpm install` 通过。
- [x] 设计令牌与样式：使用 WeKnora 的 `styles/` 与 `assets/theme/`；原 `tokens.css` 与 `tdesign-theme.css` 删除。
- [x] 国际化：使用 WeKnora 的 `i18n/locales`；补充占位页文案（`planned.*`，zh-CN 与 en-US）。品牌文案与 Nexus 术语的调整留待对应分组。
- [x] 请求层：使用 WeKnora 的 `utils/request.ts`（Bearer 令牌、`X-Tenant-ID`、刷新）。Nexus 后端的登录与令牌返回格式在第 2 组按 WeKnora 实现。
- [x] 路由：`/platform/organizations` 改为 `/platform/shared-spaces`（菜单、命令面板、页面链接同步修改）。默认入口改为 `/platform/settings`。本阶段未实现的页面（知识库、智能体、会话、产物、工具箱、自动化、创建会话）指向 `views/placeholder/PlannedPage.vue`。
- [x] 设置菜单：保留 WeKnora 的全部入口。`config/phase1.ts` 定义本阶段已实现的分区（常规、个人资料、空间信息、成员、API Key、审计）；其余分区显示占位提示。
- [x] 设置分组：保留 WeKnora `Settings.vue` 的分组与顺序（`design.md` 9.3 规定按 WeKnora 分组显示）。本阶段实现的分区见 `config/phase1.ts`，审计与成员分别在"系统管理"与"空间"分组。
- [x] 侧栏：保留 WeKnora 的全部入口（`design.md` 9.1 规定菜单项保留、页面占位）。未实现页面指向 `PlannedPage`。侧栏会话列表仍调用 WeKnora 接口，待第 2 组对接后可用。
- [ ] 类型检查与生产构建（`pnpm build`、`vue-tsc`）在有足够内存的环境中通过。

## 1. 数据模型与迁移（`packages/platform`）

- [ ] `tenants` 增加 `kind`（`personal` / `enterprise`）、`wecom_corp_id`（可空）。
- [ ] `users` 增加 `must_change_password`；邮箱唯一（沿用 WeKnora `users.email` 唯一索引）。不增加手机号字段。
- [ ] `tenant_memberships` 的角色使用 `owner` / `admin` / `contributor` / `viewer`；`source` 允许值为 `manual`、`invitation`、`application`。
- [ ] `org_units` 增加 `tenant_id`、`source`；每个企业一棵树。
- [ ] `user_org_units` 增加 `tenant_id`；主部门唯一约束为 `(tenant_id, user_id)`。
- [ ] 共享空间表结构按 WeKnora `internal/types/organization.go` 翻译，命名改为 `shared_spaces`、`shared_space_tenant_members`、`shared_space_join_requests`，共享表外键列改为 `shared_space_id`（见 `design.md` 9.5）。
- [ ] 新增 `space_join_requests`（申请与邀请）。
- [ ] 开发库重建方案（A）：单个 Alembic 迁移，不做数据回填。

## 2. 注册、登录与空间（WeKnora `auth.go`、`tenant.go`）

- [ ] `POST /auth/register`：用户名、邮箱、密码，`space_kind` 决定创建个人空间或企业空间。企业注册需要企业名称与企业编码（唯一）。注册开关由配置控制。
- [ ] `POST /auth/login`：邮箱与密码；返回用户与可选空间列表；统一失败信息。
- [ ] `POST /auth/switch-tenant`：切换空间。
- [ ] `GET /auth/me`、`PUT /auth/me/preferences`、`POST /auth/change-password`；首次登录改密时只允许改密与退出。
- [ ] `GET /tenants`、`POST /tenants`、`GET /tenants/current`、`PATCH /tenants/current`（差异见 `design.md` 9.5）。
- [ ] 前端：登录页、注册页（个人 / 企业 Tab）、空间选择页（`/onboarding/workspace`）、邀请落地页（`/join`）、首次改密页。

## 3. 成员、邀请与角色（WeKnora `tenant_member.go`、`tenant_invitation`）

- [ ] `GET/POST /tenants/:id/members`、`PUT/DELETE /tenants/:id/members/:user_id`、`POST /tenants/:id/leave`。owner 不能被移除或降级。
- [ ] `GET/POST /tenants/:id/invitations`、`DELETE .../:inv_id`、`POST /tenants/:id/invite-links`。
- [ ] `GET /me/invitations`、`.../pending-count`、`POST .../accept`、`.../decline`、`accept-by-token`。
- [ ] 管理员按邮箱添加：邮箱已存在时只能邀请，不能设置密码；不存在时创建账号并设置初始密码，首次登录改密。
- [ ] 申请加入企业：一人一企业一条待处理；撤回；审批时指定部门与角色；拒绝时填写原因，冷却 7 天。
- [ ] 按部门批量选人分配角色，逐人写入 `tenant_user_roles`。
- [ ] 所有写操作写入审计。
- [ ] 前端：空间信息页（`TenantInfo`）、成员页（`TenantMembers`）、邀请弹窗、待处理邀请列表、申请审批列表。

## 4. 共享空间（WeKnora `organization.go`、`OrganizationHandler`，本仓库命名 `shared_space`）

- [ ] `GET/POST /api/v1/shared-spaces`、`GET /api/v1/shared-spaces/search`、`GET /api/v1/shared-spaces/preview/:code`、`POST /api/v1/shared-spaces/join`、`POST /api/v1/shared-spaces/join-request`、`POST /api/v1/shared-spaces/join-by-id`、`GET/PUT/DELETE /api/v1/shared-spaces/:id`、`POST /api/v1/shared-spaces/:id/leave`、`POST /api/v1/shared-spaces/:id/request-upgrade`、`POST /api/v1/shared-spaces/:id/invite-code`。
- [ ] 共享空间内角色 `admin` / `editor` / `viewer`；权限判断沿用 WeKnora 的 `access` 逻辑。
- [ ] 前端：`/platform/shared-spaces` 列表、创建、加入、设置弹窗。界面文案为"共享空间"。
- [ ] 部门架构（扩展）：子公司与部门树的服务与接口 `/api/v1/tenants/{tenant_id}/org-units`，表仍为 `org_units`；节点规则（环检测、停用、删除前检查）沿用既有实现。界面名称为"部门架构"。
- [ ] 部门架构页面位于企业设置下，作为本仓库扩展，在 `design.md` 9.5 列明。

## 5. 权限（`packages/platform/authz`）

- [ ] 角色与权限键对照 WeKnora 的 `RBAC` 守卫（`Viewer` / `Contributor` / `Admin` / `Owner`）。
- [ ] `authz/catalog.py` 增加 `org:manage`；内置角色默认权限与 WeKnora 对应。
- [ ] 个人空间不返回企业接口（404）；企业成员角色不足时返回 403。
- [ ] 平台管理员组织接口改为只读汇总。

## 6. 设置（WeKnora `Settings.vue`）

- [ ] 分组与顺序按 `design.md` 9.3；本阶段实现的分组：常规、个人资料、空间信息、成员、API Key、组织、审计（企业）。
- [ ] 其余分组显示占位页，菜单项保留。
- [ ] 企业审计页（Admin+）读取 `GET /tenants/:id/audit-log`。

## 7. 企业微信

- [ ] 绑定时，若企业空间记录了 `wecom_corp_id`，只允许绑定到本企业账号。
- [ ] 通讯录同步不在本阶段，另开提案。

## 8. 测试

- [ ] `uv run --locked pytest`：注册两种类型；登录与多空间选择；切换空间；首次改密；邮箱已存在时管理员只能邀请；申请、审批、拒绝与冷却；邀请接受与拒绝；成员退出（owner 除外）；角色逐人写入；组织加入与权限；主部门唯一；移动成环拒绝；个人空间不暴露企业接口；企业成员 403。
- [ ] `pnpm test:browser`：注册、登录、空间选择、企业设置、组织页面。
- [ ] 每组页面与 WeKnora 逐项比对，结果写在对应分组末尾。

## 不做（本阶段）

- 企业微信通讯录同步。
- 部门级角色继承。
- 短信验证码与手机号。
- 对话、知识库、智能体等业务页面（占位，由后续子提案实现）。
- 计费与配额。
