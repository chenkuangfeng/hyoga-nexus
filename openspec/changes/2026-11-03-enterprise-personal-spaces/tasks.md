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

- [x] `tenants` 增加 `kind`（`personal` / `enterprise`）、`wecom_corp_id`（可空）。
- [x] `users` 增加 `must_change_password`；邮箱唯一（沿用 WeKnora `users.email` 唯一索引）。不增加手机号字段。
- [x] `tenant_memberships` 的角色使用 `owner` / `admin` / `contributor` / `viewer`；`source` 允许值为 `manual`、`invitation`、`application`。
- [x] `org_units` 增加 `tenant_id`、`source`；每个企业一棵树。
- [x] `user_org_units` 增加 `tenant_id`；主部门唯一约束为 `(tenant_id, user_id)`。
- [x] 共享空间表结构按 WeKnora `internal/types/organization.go` 翻译，命名改为 `shared_spaces`、`shared_space_tenant_members`、`shared_space_join_requests`，共享表外键列改为 `shared_space_id`（见 `design.md` 9.5）。
- [x] 新增 `space_join_requests`（申请与邀请）。
- [x] 开发库重建方案（A）：单个 Alembic 迁移，不做数据回填。
- 实施说明（2026-11-03）：迁移 `b8e2f1c4d7a9_enterprise_spaces` 为开发库重建方案，不回填数据；`tenant_org_bindings` 删除，`sessions.org_unit_id` 删除，机构节点不再参与访问判断。角色枚举改为 `owner` / `admin` / `contributor` / `viewer`，`TenantRole.MEMBER` 同步改名。`org:manage` 加入 `API_PERMISSIONS`，owner 与 admin 通过内置完整目录获得。机构服务与接口改为企业范围（`/api/v1/tenants/{tenant_id}/org-units`），旧的绑定、平台管理员全局视图与 `from-organization` 批量加入已移除，分别在第 4、5、3 组重新实现。测试：`tests/test_org_tree.py` 覆盖一企业一棵树、主节点唯一、成环拒绝、停用与删除规则、撤销成员不计入人数；全量 `pytest` 553 通过，1 跳过。


## 2. 注册、登录与空间（WeKnora `auth.go`、`tenant.go`）

- [x] `POST /api/v1/auth/register`：用户名、邮箱、密码，`space_kind`（默认 `personal`）决定创建个人空间或企业空间。企业注册需要企业名称与企业编码（唯一，`tenants.code`）。注册开关为 `[auth].registration_enabled`，关闭时返回 403。
- [x] `POST /api/v1/auth/login`：邮箱与密码；返回 `user`、`memberships`、默认空间 `tenant`（个人空间优先）与 `token`；失败信息统一，连续 5 次锁定 15 分钟。
- [x] `POST /api/v1/auth/switch-tenant`：校验成员身份后返回空间。与设计稿 9.2 的差异见 `design.md` 9.5：令牌不变，空间由请求头 `X-Tenant-ID` 逐次指定并校验成员身份。
- [x] `GET /api/v1/auth/me`、`POST /api/v1/auth/change-password`（`/auth/password` 作为别名保留）。`must_change_password` 为真时，除 `/auth/me`、退出与改密外的接口返回 403。
- [x] `PUT /api/v1/auth/me/preferences`：`users.preferences` 存储；`last_active_tenant_id` 仅在仍是有效成员时于登录沿用，空值清除；未知键返回 422。`browser_search_instructions`、`gallery` 按原样保存。`tests/test_registration_spaces.py` 覆盖。
- [x] `GET /api/v1/tenants/current`、`PATCH /api/v1/tenants/current`（owner、admin 可改名与描述）；`GET /api/v1/tenants`、`POST /api/v1/tenants` 沿用。
- [x] Bearer 令牌：`Authorization: Bearer <token>`，无需 CSRF 头；Cookie 登录仍保留（企业微信回调使用）。
- [x] 前端：改初始密码页（`/auth/change-password`），登录后若需改密则跳转。
- [x] 租户 ID 统一为 UUID 字符串：前端副本中约 70 处数字类型的租户 ID 与 `Number(...)` 转换已改为字符串，登录后总是选中当前空间并发送 `X-Tenant-ID`（`App.vue`、`views/auth/Login.vue`）。`tsc -p tsconfig.app.json` 对 `.ts` 文件无错误；`.vue` 文件仅做语法检查（`vue-tsc` 本机内存不足）。
- [ ] 前端：注册页的企业 Tab、空间选择页（`/onboarding/workspace`）、邀请落地页（`/join`）仍是 WeKnora 复制版的原样，尚未按 Nexus 接口调整。
- [ ] 前端：`/auth/config`、`/auth/oidc/*`、`/auth/auto-setup` 等 WeKnora 启动接口在本仓库尚未实现，启动时会返回 404。
- 实施说明（2026-11-03）：测试 `tests/test_auth.py`（改为邮箱登录，覆盖改密门禁）与 `tests/test_registration_spaces.py`（注册两类空间、编码唯一、注册开关、Bearer、空间选择与改名）。全量 pytest 通过。前端仅做语法检查（本机构建内存不足，以 CI 为准）。

## 3. 成员、邀请与角色（WeKnora `tenant_member.go`、`tenant_invitation`）

- [x] 成员列表 `GET /api/v1/tenants/:id/members`、角色修改 `PATCH .../members/:member_id`（沿用，WeKnora 为 `PUT`，见 `design.md` 9.5）、移除 `DELETE .../members/:member_id`（owner 不能被移除或降级，最后一个 owner 不能移除）。
- [x] 离开空间 `POST /api/v1/tenants/:id/leave`；owner 不能直接离开。
- [x] 按邮箱添加 `POST /api/v1/tenants/:id/members/by-email`：邮箱已有账号时只生成邀请；邮箱没有账号时，需要提供用户名与初始密码创建账号，首次登录改密。
- [x] 邀请列表与撤销：`GET /api/v1/tenants/:id/invitations`、`DELETE .../invitations/:inv_id`。
- [x] 用户侧邀请：`GET /api/v1/me/invitations`、`.../pending-count`、`POST .../accept`、`POST .../decline`。
- [ ] 邀请链接 `POST /api/v1/tenants/:id/invite-links` 与 `accept-by-token` 未实现（需要令牌存储，留到后续）。
- [x] 申请加入企业：`POST /api/v1/tenants/:id/join-requests`（一人一企业一条待处理；个人空间不接受申请）；撤回 `DELETE .../join-requests/:id`；列表 `GET .../join-requests`。
- [x] 审批：`POST .../join-requests/:id/approve` 必须指定部门与角色（角色不能是 owner）；拒绝 `POST .../reject` 必须填写原因，之后 7 天内不能再次申请。
- [x] 按部门批量分配自定义角色 `POST /api/v1/tenants/:id/org-units/:unit_id/role-assignments`：逐人写入 `tenant_user_roles`，跳过 owner、admin 与已有该角色的人，可重复调用。
- [x] 所有写操作写入审计（`audit_records`）。
- [x] 前端成员与邀请接口封装（`api/tenant/members.ts`、`api/tenant/invitations.ts`）已对接 Nexus 端点与返回结构：成员列表含邮箱、用户名、显示名（`MemberView` 增加字段）；按邮箱邀请；待处理邀请列表；接受与拒绝；撤销。成员页与邀请列表沿用原组件。
- [x] 空间信息页（`TenantInfo`）改名与描述通过 `PATCH /api/v1/tenants/current`（owner、admin；`description` 可清空，最长 500 字）；删除空间通过 `DELETE /api/v1/tenants/:id`（仅企业空间的 owner；个人空间返回 403；仍创建着有效共享空间时返回 409；删除为归档，成员列表中消失，之后访问返回 404）。`tests/test_registration_spaces.py`、`tests/test_shared_spaces.py` 覆盖。
- [ ] 前端：成员页的邀请链接弹窗与申请审批列表尚未按新接口调整；邀请链接与令牌加入未实现，相关调用会得到 404。
- [ ] 前端：按邮箱添加且邮箱无账号时，后端需要用户名与初始密码，成员页尚未提供这两个输入项。
- 实施说明（2026-11-03）：测试 `tests/test_membership_flows.py` 通过 HTTP 覆盖邀请、接受与拒绝、按邮箱建账号、申请与审批、拒绝冷却、撤回、离开、批量角色。全量 pytest 569 通过。

## 4. 共享空间（WeKnora `organization.go`、`OrganizationHandler`，本仓库命名 `shared_space`）

- [x] `GET/POST /api/v1/shared-spaces`、`GET /api/v1/shared-spaces/search`、`GET /api/v1/shared-spaces/preview/:code`、`POST /api/v1/shared-spaces/join`、`POST /api/v1/shared-spaces/join-request`、`POST /api/v1/shared-spaces/join-by-id`、`GET/PUT/DELETE /api/v1/shared-spaces/:id`、`POST /api/v1/shared-spaces/:id/leave`、`POST /api/v1/shared-spaces/:id/request-upgrade`、`POST /api/v1/shared-spaces/:id/invite-code`。以上均需要 `X-Tenant-ID`（搜索与预览除外）。
- [x] 补充：`GET /api/v1/shared-spaces/:id/join-requests` 与 `.../join-requests/:req_id/approve|reject`（审批加入与升级申请，WeKnora 同样提供）。
- [x] 共享空间内角色 `admin` / `editor` / `viewer`。空间（而非人）加入共享空间；创建方空间为 admin 且不能退出，只能删除（软删除）。
- [x] 加入规则：邀请码（有效期可设）、直接加入（需 `searchable` 且不需要审批）、申请（`require_approval` 时直接加入也转为申请）。申请与升级共用 `shared_space_join_requests`，与人员加入的 `space_join_requests` 分开。
- [ ] 资源共享的有效权限（WeKnora `kbshare.go`：取共享方、所属空间角色、调用方上限三者的最小值）尚未实现，属于知识库与智能体的共享，待对应模块接入。
- [x] 前端：`/platform/shared-spaces` 页面（`views/shared-space/SharedSpaceList.vue`，接口封装 `api/shared-space`）：列表、创建、邀请码预览与加入、详情中的成员与设置、邀请码重新生成、申请审批与拒绝、离开与删除。界面文案为"共享空间"。知识库与智能体的共享设置仍是 WeKnora 原样（依赖未实现的资源共享接口），待对应模块接入。
- [x] 部门架构（扩展）：服务与接口 `/api/v1/tenants/{tenant_id}/org-units` 已在第 1 组实现，表仍为 `org_units`。
- [ ] 部门架构页面（企业设置下）尚未实现，见第 6 组。
- 实施说明（2026-11-03）：测试 `tests/test_shared_spaces.py` 覆盖创建、邀请码与预览、直接加入与审批、升级申请、离开与删除、角色限制。`shared_spaces` 包位于 `packages/platform/src/nexus_platform/shared_spaces/`。

## 5. 权限（`packages/platform/authz`）

- [x] 角色与权限键按设计稿第 4 节实现（2026-11-03 确认"按设计稿"）：owner 拥有全部权限；admin 拥有内置权限，但不含 `org:manage`、`members:manage`、`roles:manage`、`audit:read`，这四项只能通过自定义角色获得；member（contributor、viewer）只有自定义角色授予的权限。管理员仍可获得自定义角色（`tenants/roles.py` 不再拒绝）。WeKnora 的 `RBAC` 四档映射见 `design.md` 第 4 节。
- [x] `authz/catalog.py` 增加 `org:manage`；owner 与 admin 通过内置完整目录获得。
- [x] 个人空间不返回企业接口：成员管理、邀请、申请、部门架构返回 404（`tests/test_space_scope.py`）。企业成员角色不足时返回 403。
- [x] 平台管理员组织接口改为只读汇总：`GET /api/v1/admin/summary`（企业、个人空间、共享空间数量）。全局部门与绑定接口已删除（第 1 组）。

## 6. 设置（WeKnora `Settings.vue`）

- [ ] 分组与顺序按 `design.md` 9.3 在前端实现（第 0 组已保留分组与占位，本阶段实现分区的页面逐项对接尚未完成）。
- [x] 其余分组显示占位页，菜单项保留（第 0 组）。
- [x] 企业审计接口：`GET /api/v1/tenants/:id/audit-log`（与既有 `/audit` 相同，需要 `audit:read`；owner 始终拥有，admin 需自定义角色）。
- [ ] 前端：企业审计页、空间信息页、成员页、部门架构页尚未按新接口调整。

## 7. 企业微信

- [x] 绑定时，若企业空间记录了 `wecom_corp_id`，只允许该企业的有效成员绑定（`auth/wecom.py`，`tests/test_wecom_corp_scope.py`）。目前没有界面设置该字段，只能由数据库记录。
- [ ] 通讯录同步不在本阶段，另开提案。

## 8. 测试

- [x] `uv run --locked pytest`：注册两种类型（`test_registration_spaces.py`）；登录与空间选择；切换空间；首次改密（`test_auth.py`）；邀请、申请、审批、拒绝与冷却、撤回、离开、批量角色（`test_membership_flows.py`）；共享空间（`test_shared_spaces.py`）；部门主节点唯一、成环拒绝（`test_org_tree.py`）；个人空间不暴露企业接口、企业成员 403（`test_space_scope.py`）。全量 579 通过，1 跳过。
- [ ] `pnpm test:browser`：注册、登录、空间选择、企业设置、组织页面（前端未对接，未执行）。
- [ ] 每组页面与 WeKnora 逐项比对，结果写在对应分组末尾（前端对接后进行）。

## 不做（本阶段）

- 企业微信通讯录同步。
- 部门级角色继承。
- 短信验证码与手机号。
- 对话、知识库、智能体等业务页面（占位，由后续子提案实现）。
- 计费与配额。
