# 实施任务

状态：草案第三版，待用户最终确认（2026-11-11）；需要确认的项 1、3 已确认，剩第 2 项。确认前不开始编码。各阶段开始前在 `design.md` 补齐细节并经确认，实施中发现的追加工作写入本文件。

## E0 资源归属与维护权

- [ ] E0.1 迁移：`agents.ownership`、`knowledge_bases.ownership`（现有数据设为 `enterprise`）；`knowledge_base_maintainers`；`tenant_agent_grants` 中的 `edit`、`publish`、`manage` 降为 `run`。
- [ ] E0.2 权限：`enterprise_agents:manage`、`enterprise_kbs:manage`；`can_maintain_agent`、`can_use_agent`、`can_manage_kb`、`can_maintain_kb_content`（`design.md` 2.2）；`AGENT_PERMISSIONS` 收窄为 `view`、`run`。
- [ ] E0.3 接口：工作台的创建接口写入 `personal`，管理后台的创建接口写入 `enterprise`；知识库管理员的增删查；个人资源治理（查看、停用、删除、转为企业资源，视需要确认的项 1）；列表与详情返回 `ownership`、`can_maintain`。
- [ ] E0.4 绑定检查：企业智能体不能绑定个人知识库；绑定范围覆盖检查。
- [ ] E0.5 测试：两种归属的维护权矩阵；共享只授予使用；知识库管理员只能维护内容；绑定方向；审计 detail。
- [ ] E0.6 文档：`docs/architecture.md` 2.10、2.11 与相关模块文档。

## E1 租户与个人区

- [ ] E1.1 迁移：删除 `personal` 租户及数据并收紧 `kind` 约束；`knowledge_bases.visibility`；`enterprise_policies`；`tenant_roles.builtin`。
- [ ] E1.2 注册只创建企业；删除个人空间相关的后端分支与测试；登录默认进入上次使用的企业。
- [ ] E1.3 知识库可见范围：`can_read` 按可见范围判断；修改可见范围的冲突检查。
- [ ] E1.4 企业策略：接口与三处检查。
- [ ] E1.5 企业级管理角色与审计正文权限。
- [ ] E1.6 删除跨企业的 `/admin/*` 接口及服务函数与测试。
- [ ] E1.7 测试：注册即创建企业、可见性矩阵、三项策略、内置角色不可删除。
- [ ] E1.8 PostgreSQL 门禁：完成路线图 2.9，并覆盖本提案新增的列与表。
- [ ] E1.9 文档：`docs/architecture.md`、`docs/roadmap.md`（新增企业化步骤，2.9 改为前置门禁，9.1 由 E4 承接）、`configs/README.md`、`README.md`。

## E2 前端重构

- [ ] E2.1 建立 pnpm workspace：根 `package.json`、`pnpm-workspace.yaml`（含 catalog）、`tsconfig.base.json`；`core`、`workspace`、`admin` 骨架；边界检查测试。
- [ ] E2.2 删除清单（`design.md` 4.5），含连带的依赖、文案与测试。
- [ ] E2.3 抽取 `core`：请求层与接口、store、composables、directives、utils、types、i18n、样式与主题、共用组件（登录与扫码登录、改密、企业切换、布局骨架、空状态、错误页、文档预览、Markdown、智能体编辑器、知识库编辑器、IM 渠道面板）。
- [ ] E2.4 员工工作台：对话、我的智能体、我的知识库、我维护的企业知识库、企业分配、技能、记忆、产物、自动化、共享空间、个人设置；单智能体模式；`embed.html` 第二入口；手机宽度布局。
- [ ] E2.5 企业管理后台：企业信息、成员、部门架构、角色与权限、企业策略、企业智能体、企业知识库（含知识库管理员）、个人资源治理、模型、工具与技能、MCP、存储与检索、共享空间、运行状况、审计。
- [ ] E2.6 后端配合：`/auth/me` 的 `entries`；管理接口前缀 `/api/v1/tenants/{id}/admin/...`（旧路径保留一个版本周期）。
- [ ] E2.7 外部向量库与存储后端连接接入网络出口策略，并补私有地址被拒的测试。
- [ ] E2.8 构建与测试：`pnpm build` 产出两份产物且工作台不含管理后台代码；`pnpm type-check`、`pnpm test`、两个应用的浏览器测试；记录本机构建的内存情况。
- [ ] E2.9 文档：`AGENTS.md` 前端命令（并更正其中“Element Plus”的旧描述）；`apps/web` 父模块文档与三个项目的 `README.md`；`docs/architecture.md` 1.4 与 2.15；反向代理示例。

## E3 企业微信：企业、多应用与登录

- [ ] E3.0 核对企微官方文档（`design.md` 6.4 与 7.2 所列各项），结果记入设计。
- [ ] E3.1 `tenant_wecom_corps`、`tenant_wecom_apps`；删除 `configs [wecom]`；管理后台的企业绑定与应用列表页（主页地址复制、扫码登录标记）。
- [ ] E3.2 企微内免登：`/wecom/apps/{app_id}/entry` 与回调；按用途跳转；自动开户。
- [ ] E3.3 扫码登录：按企业编码找到扫码应用；登录页入口。
- [ ] E3.4 通讯录回调验签解密；全量同步与增量；离职撤销成员身份。
- [ ] E3.5 测试：三种用途的跳转与权限拒绝、一个智能体至多一个应用、扫码登录、自动开户、离职后请求被拒；用假的 `WeComDirectory`。

## E4 IM 渠道

- [ ] E4.1 `agent_channels`、`channel_identities`、`channel_session_bindings`。
- [ ] E4.2 企微智能机器人渠道：接收、去重、身份映射、使用权检查、会话隔离、以发送者身份运行、回复与截断、确认类工具的提示。
- [ ] E4.3 `agent` 用途自建应用的消息会话渠道。
- [ ] E4.4 智能体“渠道”页（管理后台的企业智能体；个人智能体视需要确认的项 2）。
- [ ] E4.5 测试：群聊中不同成员互不混入、无使用权的回复、离职成员被拒、重复消息只处理一次。

## E5 组织驱动授权

- [ ] E5.1 `agent_principal_grants` 与知识库按部门、成员开放；部门子树展开。
- [ ] E5.2 前端：分配与共享对话框增加部门与成员。

## E6 成本与配额

- [ ] E6.1 `usage_ledger` 累加与用量报表。
- [ ] E6.2 三级月度上限的准入检查。

## E7 数据治理

- [ ] E7.1 按 `retention_days` 留存清理。
- [ ] E7.2 审计导出与哈希链。

## 收尾

- [ ] 同步 OpenSpec 规格、路线图与模块文档后归档。
