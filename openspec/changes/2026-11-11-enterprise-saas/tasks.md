# 实施任务

状态：草案，待确认（2026-11-11）。确认 `proposal.md` 中“需要你确认的项”之前不开始编码。各阶段开始前在 `design.md` 补齐细节并经确认，实施中发现的追加工作写入本文件。

## E0 知识库维护开放给智能体管理员

- [ ] E0.1 `knowledge/access.py` 新增 `can_maintain_content`（`design.md` 第 2 节），文档、分块、问答的写接口改用它；库设置、删除、共享仍用 `can_write`。
- [ ] E0.2 接口返回 `can_maintain`；通过这条路径的写入在审计中记录 `via_agent_id`。
- [ ] E0.3 前端：知识库列表与详情按 `can_maintain` 显示维护入口。
- [ ] E0.4 测试：有 `manage` 可维护；只有 `edit` 不可维护；解绑或撤权后立即失去权限；不能删除库、修改设置或共享；共享来的库仍然只读。
- [ ] E0.5 文档：`docs/architecture.md` 2.10 与 `packages/knowledge` 的模块文档。

## E1 租户与个人区

- [ ] E1.1 迁移：`tenants.plan`；`knowledge_bases.visibility`；新表 `enterprise_policies`；`tenant_roles.builtin`；按需要确认的项 2 处理 `personal`。
- [ ] E1.2 注册改为只创建单人试用企业；`tenants/plan.py` 试用限制与各检查点；命令行 `upgrade-enterprise`。
- [ ] E1.3 登录默认空间改为上次使用的企业；空间选择页去掉个人空间。
- [ ] E1.4 私有知识库：`can_read` 按可见范围判断；修改可见范围的冲突检查；智能体发布时的绑定范围检查。
- [ ] E1.5 企业策略：读取与修改接口（`policy:manage`）；在创建智能体、模型选择与 Run 准备、共享到共享空间三处检查。
- [ ] E1.6 企业级管理角色：`policy:manage`、`audit:read_content`；内置 `security_admin` 与 `auditor`；审计正文的查看权限与留痕。
- [ ] E1.7 测试：试用限制与转正、私有库可见性矩阵、绑定范围拦截、三项策略、内置角色不可删除、不能新建个人空间。
- [ ] E1.8 PostgreSQL 门禁：完成路线图 2.9，并覆盖本阶段新增的列与表。
- [ ] E1.9 文档：`docs/architecture.md` 2.10、2.11、`docs/roadmap.md`（新增企业化步骤，2.9 改为前置门禁）、`configs/README.md`、`README.md`。

## E2 前端两个入口

- [ ] E2.1 `/auth/me` 返回 `entries`；管理接口前缀 `/api/v1/tenants/{id}/admin/...`，旧路径保留一个版本周期。
- [ ] E2.2 路由与布局拆成 `/workspace` 与 `/admin`，管理后台独立分包；`/platform/*` 重定向。
- [ ] E2.3 `config/settingsAccess.ts` 改为按入口和权限归属（`design.md` 第 4 节表格），`Settings.vue` 拆为工作台的个人设置与管理后台的各个分区。
- [ ] E2.4 工作台导航：“我的”与“企业共享”分组；我的审批待办入口（E4 之前只显示本人的审批）。
- [ ] E2.5 管理后台：企业策略分区、知识库治理、内置角色。
- [ ] E2.6 手机宽度布局（工作台）；浏览器测试覆盖两个入口的权限跳转与手机布局。

## E3 企业微信

- [ ] E3.0 核对企微官方文档：代开发与自建两种模式下，登录、部门、成员、直属上级、回调、应用消息、模板卡片各接口的可用字段与限制，结果记入 `design.md` 第 5 节。
- [ ] E3.1 `tenant_wecom_apps` 与管理后台的配置页（加密保存密钥）；回调验签与解密。
- [ ] E3.2 扫码与企微内免登；已同步成员首次进入时自动开户。
- [ ] E3.3 通讯录全量同步与回调增量；`user_managers`。
- [ ] E3.4 离职处理：撤销成员身份、ActionGrant、MCP 令牌与定时任务；资产移交；审计。
- [ ] E3.5 企微消息渠道（承接路线图 9.1）。

## E4 组织驱动授权与审批

- [ ] E4.1 `agent_principal_grants` 与资源授权的部门、成员接收方；知识库按部门开放；部门子树展开。
- [ ] E4.2 审批人路由（`self`、`manager`、`resource_owner`、`role`）、审批超时、工作台待办。
- [ ] E4.3 企微审批卡片。

## E5 成本与配额

- [ ] E5.1 `usage_ledger` 累加与用量报表（企业、部门、个人、智能体、模型）。
- [ ] E5.2 三级月度上限的准入检查。

## E6 数据治理

- [ ] E6.1 留存清理与法务保全。
- [ ] E6.2 审计导出与哈希链。
- [ ] E6.3 离职成员的记忆处理。

## 收尾

- [ ] 同步 OpenSpec 规格、路线图与模块文档后归档。
