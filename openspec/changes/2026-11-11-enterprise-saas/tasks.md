# 实施任务

状态：草案第二版，待用户最终确认（2026-11-11）。确认前不开始编码。各阶段开始前在 `design.md` 补齐细节并经确认，实施中发现的追加工作写入本文件。

## E0 知识库维护开放给智能体创建者

- [ ] E0.1 `knowledge/access.py` 新增 `can_maintain_content`（`design.md` 第 2 节），文档、分块、问答的写接口改用它；库设置、删除、共享仍用 `can_write`。
- [ ] E0.2 接口返回 `can_maintain`；通过这条路径的写入在审计中记录 `via_agent_id`。
- [ ] E0.3 前端：知识库列表与详情按 `can_maintain` 显示维护入口。
- [ ] E0.4 测试：智能体创建者可维护；只经角色授权获得 `manage` 的人不可维护；解绑后立即失去权限；不能删除库、修改设置或共享；共享来的库仍然只读。
- [ ] E0.5 文档：`docs/architecture.md` 2.10 与 `packages/knowledge` 的模块文档。

## E1 租户与个人区

- [ ] E1.1 迁移：删除 `personal` 租户及数据并收紧 `kind` 约束；`knowledge_bases.visibility`；新表 `enterprise_policies`；`tenant_roles.builtin`。
- [ ] E1.2 注册改为只创建企业（名称与编码选填、缺省自动生成）；删除个人空间相关的后端分支与测试。
- [ ] E1.3 登录默认进入上次使用的企业；不属于任何企业的账号进入“创建或加入企业”页。
- [ ] E1.4 私有知识库：`can_read` 按可见范围判断；修改可见范围的冲突检查；智能体发布时的绑定范围检查。
- [ ] E1.5 企业策略：读取与修改接口（`policy:manage`）；在创建智能体、模型选择与 Run 准备、共享到共享空间三处检查。
- [ ] E1.6 企业级管理角色：`policy:manage`、`audit:read_content`；内置 `security_admin` 与 `auditor`；审计正文的查看权限与留痕。
- [ ] E1.7 删除跨企业的 `/admin/tenants`、`/admin/summary`、`/admin/agents`、`/admin/sessions` 接口及对应服务函数与测试。
- [ ] E1.8 测试：注册即创建企业、私有库可见性矩阵、绑定范围拦截、三项策略、内置角色不可删除。
- [ ] E1.9 PostgreSQL 门禁：完成路线图 2.9，并覆盖本阶段新增的列与表。
- [ ] E1.10 文档：`docs/architecture.md` 2.10、2.11、`docs/roadmap.md`（新增企业化步骤，2.9 改为前置门禁）、`configs/README.md`、`README.md`。

## E2 前端重构

- [ ] E2.1 建立 pnpm workspace：`apps/web` 根的 `package.json`、`pnpm-workspace.yaml`（含 catalog）、`tsconfig.base.json`；`core`、`workspace`、`admin` 三个项目骨架；边界检查测试。
- [ ] E2.2 删除清单（`design.md` 4.5）：平台管理、助手、Ollama、WeKnora Cloud、CLI、Chrome 插件、Claw 技能、WeKnora API Key 与 IM 页、本地浏览器连接、桌面壳、个人空间入口，以及连带的依赖、文案与测试。
- [ ] E2.3 抽取 `core`：请求层与接口函数、auth 与 tenant 等 store、composables、directives、utils、types、i18n 工厂与公共文案、样式与主题、两个应用共用的组件（登录、改密、企业切换、布局骨架、空状态、错误页、文档预览、Markdown 渲染）。
- [ ] E2.4 员工工作台：迁入对话、我的智能体、我的知识库、我的技能、我的记忆、我的产物、我的自动化、企业共享、共享空间、个人设置；“对话”“我的”“企业共享”“个人设置”四组导航；`embed.html` 第二入口；手机宽度布局。
- [ ] E2.5 企业管理后台：迁入企业信息、成员、部门架构、角色与权限、模型、工具与技能、MCP、存储与检索、共享空间、审计；新增企业策略、智能体治理（停用、删除）、知识库治理、运行状况页面。
- [ ] E2.6 后端配合：`/auth/me` 返回 `entries`；管理接口前缀 `/api/v1/tenants/{id}/admin/...`（旧路径保留一个版本周期）；智能体与知识库列表返回 `owned_by_me`、`visibility`。
- [ ] E2.7 外部向量库与存储后端的连接接入网络出口策略，并补私有地址被拒的测试。
- [ ] E2.8 构建与测试：`pnpm build` 产出两份静态产物且工作台不含管理后台代码；`pnpm type-check`、`pnpm test`、两个应用的浏览器测试（权限跳转、手机布局）；记录本机构建的内存情况。
- [ ] E2.9 文档：`AGENTS.md` 前端构建命令；`apps/web/README.md` 与 `docs/`（父模块，汇总三个项目）；`core`、`workspace`、`admin` 的 `README.md`；`docs/architecture.md` 1.4 目录结构与 2.15 Web 工作台；部署示例的反向代理配置。

## E3 企业微信自建应用

- [ ] E3.0 核对企微官方文档：自建应用在登录、部门、成员、回调、应用消息各接口的可用字段与限制，结果记入 `design.md` 第 6 节。
- [ ] E3.1 `tenant_wecom_apps` 与管理后台的配置页（加密保存密钥）；删除 `configs [wecom]`；回调验签与解密。
- [ ] E3.2 扫码与企微内免登；已同步成员首次进入时自动开户。
- [ ] E3.3 通讯录全量同步与回调增量。
- [ ] E3.4 离职：撤销企业成员身份并写入审计，资产不动。
- [ ] E3.5 企微消息渠道（承接路线图 9.1）。

## E4 组织驱动授权

- [ ] E4.1 `agent_principal_grants` 与资源授权的部门、成员接收方；部门子树展开。
- [ ] E4.2 知识库按部门、成员开放；发布检查改为“覆盖使用范围”。
- [ ] E4.3 前端：智能体与知识库的共享对话框增加部门与成员。

## E5 成本与配额

- [ ] E5.1 `usage_ledger` 累加与用量报表（企业、部门、个人、智能体、模型）。
- [ ] E5.2 三级月度上限的准入检查。

## E6 数据治理

- [ ] E6.1 按 `retention_days` 留存清理。
- [ ] E6.2 审计导出与哈希链。

## 收尾

- [ ] 同步 OpenSpec 规格、路线图与模块文档后归档。
