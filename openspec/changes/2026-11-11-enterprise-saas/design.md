# 设计

本文件写 E0–E4 的设计（含前端工程结构、企微多应用与 IM 渠道）、两个应用的功能清单与部署级配置的去向，以及 E5–E7 的要点。各阶段开始前补齐接口与表结构，并经用户确认。

## 1. 租户模型

```text
部署（共享数据库、共享表，按 tenant_id 隔离）
  ├─ 企业 A（tenants.kind = 'enterprise'）
  │    ├─ enterprise_policies
  │    ├─ 企微：tenant_wecom_corps（一个 corp_id）→ tenant_wecom_apps（多个自建应用：workspace / admin / agent）
  │    ├─ 组织树（org_units / user_org_units，source = manual | wecom）
  │    ├─ 成员（tenant_memberships，source 增加 wecom）与角色（含 security_admin、auditor）
  │    ├─ 企业资源：ownership = enterprise 的智能体、知识库（企业管理员维护；知识库可指定知识库管理员）
  │    ├─ 个人资源：ownership = personal 的智能体、知识库（创建者维护）
  │    ├─ 每个成员的会话、记忆、产物（本人隔离）
  │    └─ IM 渠道（每个绑定一个智能体）
  ├─ 企业 B（只有一个成员，与企业 A 没有任何区别）
  └─ 共享空间（跨企业协作，受各企业的 external_sharing 约束）
```

- **多租户方式**：共享库、共享表，用行级的 `tenant_id` 隔离，复合外键保证引用不跨企业。PostgreSQL RLS 暂不启用，见第 9 节。
- **只收紧**：平台守卫 ⊇ 企业策略 ⊇ 空间角色与资源授权。
- **执行时复核**：归属、维护权、策略、组织关系、成员状态在每次请求和每次工具调用时重新查询，不进入 Run 快照。

## 2. E0 资源归属与维护权

### 2.1 数据

- `agents.ownership`、`knowledge_bases.ownership`：`personal` 或 `enterprise`，非空。迁移时现有数据一律设为 `enterprise`。
- 新表 `knowledge_base_maintainers(tenant_id, kb_id, user_id, granted_by, granted_at)`，主键 `(kb_id, user_id)`，复合外键保证 kb 与成员同属一个企业。只对 `ownership = 'enterprise'` 的库有效。
- `authz/catalog.py` 新增 API 权限 `enterprise_agents:manage`、`enterprise_kbs:manage`，owner、admin 默认持有，可以授予自定义角色。

### 2.2 判断函数

`agents/access.py`：

```python
def can_maintain_agent(db, agent, user_id) -> bool:
    """personal：调用者是创建者；enterprise：调用者持有 enterprise_agents:manage（含 owner、admin）。"""

def can_use_agent(db, agent, user_id) -> bool:
    """可以维护，或者经分配、共享获得使用权（角色；E5 起含部门、成员；共享空间）。"""
```

`knowledge/access.py`：

```python
def can_manage_kb(db, kb, user_id) -> bool:
    """设置、可见范围、删除、共享、维护人员。personal：创建者；enterprise：enterprise_kbs:manage。"""

def can_maintain_kb_content(db, kb, user_id) -> bool:
    """文档、分块、问答。can_manage_kb，或者（enterprise 且）在 knowledge_base_maintainers 中。"""
```

- 企业 owner、admin 对个人资源只有治理操作：查看、停用、删除、转为企业资源（已确认），不能编辑内容。
- 智能体级授权（`tenant_agent_grants`）只保留 `view`、`run`。迁移把现有的 `edit`、`publish`、`manage` 降为 `run`，`AGENT_PERMISSIONS` 与 `AGENT_IMPLIED` 同步收窄；编辑、发布、管理一律走 `can_maintain_agent`。
- 绑定检查（智能体草稿保存与发布时）：
  - 企业智能体只能绑定企业知识库；
  - 个人智能体可以绑定自己的个人知识库，以及 `visibility = 'tenant'` 的企业知识库；
  - 绑定的知识库可见范围必须覆盖智能体的使用范围，否则返回 422 `binding_scope_narrower`。
- 创建入口：工作台的创建接口固定写入 `personal`（受企业策略 `self_build_agents` 约束）；管理后台的创建接口固定写入 `enterprise`（需要 `enterprise_*:manage`）。归属不由请求参数决定。
- 审计：维护操作的 detail 记录 `ownership` 与判断依据（`creator`、`enterprise_admin`、`kb_maintainer`）。

## 3. E1 租户与个人区

### 3.1 注册即创建企业，删除个人空间

- 迁移：删除 `kind = 'personal'` 的租户及其全部数据（开发库，不回填）；`ck_tenants_kind` 只允许 `enterprise` 与 `system`。
- `auth/accounts.py` `register`：去掉 `space_kind`，一律创建企业；企业名称缺省为“{显示名}的企业”，编码缺省为随机生成且全局唯一。
- 删除个人空间相关的分支（`tenants/service.py`、`models/provider_settings.py`、`http/auth.py`、`http/model_settings.py`）与测试。
- 登录默认进入 `last_active_tenant_id`，没有时进入最早加入的企业；不属于任何企业的账号进入“创建或加入企业”页。

### 3.2 知识库可见范围

- `knowledge_bases.visibility`：`private` 或 `tenant`，非空；迁移时现有知识库设为 `tenant`；新建个人知识库默认 `private`，新建企业知识库默认 `tenant`。
- `can_read`：`tenant` 对全体成员放行；`private` 只对 `can_maintain_kb_content` 成立的人与企业 owner、admin 放行。只有 `tenant` 的库才能共享到共享空间。
- 从 `tenant` 改为 `private` 时，如有其他人可用的智能体绑定了这个库，拒绝修改（409 `kb_in_use`）并列出这些智能体。

### 3.3 企业策略

`enterprise_policies(tenant_id PK, self_build_agents, self_build_org_unit_ids JSON, personal_models, external_sharing, personal_wecom_channels, personal_external_channels, retention_days, updated_by, updated_at)`；企业创建时写入默认行。读取对所有成员开放，修改需要 `policy:manage`。检查点：创建个人智能体（`self_build_agents`，企业 owner、admin 不受限）；模型选择、发布与 Run 准备（`personal_models`）；共享到共享空间（`external_sharing`）。

### 3.4 企业级管理角色

- `policy:manage`、`audit:read_content` 纳入 `GOVERNANCE_APIS`。
- `tenant_roles.builtin`；企业创建时写入 `security_admin`（`policy:manage`、`tools:manage`、`audit:read`）与 `auditor`（`audit:read`），已有企业由迁移补齐；内置角色不能删除、不能改名。
- 只有 `audit:read_content` 能看到对话正文与工具参数，每次查看写入审计。

### 3.5 删除跨企业接口

删除 `http/platform.py` 中的 `/admin/tenants`、`/admin/summary`、`/admin/agents`、`/admin/sessions`，以及 `list_all_tenants`、`platform_summary`、`list_all_agents_for_platform_admin`、`list_sessions_for_platform_admin` 与测试。

### 3.6 PostgreSQL 门禁

路线图 2.9 的全部项目，加上本提案新增的列与表，在 PostgreSQL 上完成迁移往返和并发测试后，E1 才算验收。

## 4. E2 前端工程结构

### 4.1 目录

```text
apps/web/                         pnpm workspace 根（不是应用）
├── package.json                  workspace 脚本与共用开发依赖，private
├── pnpm-workspace.yaml           packages: [core, workspace, admin]；catalog 统一依赖版本
├── pnpm-lock.yaml                唯一锁文件
├── tsconfig.base.json            共用编译选项
├── README.md、docs/              父模块文档（汇总三个项目）
├── core/                         @nexus-web/core：共用部分，源码包，不构建、不部署
│   └── src/
│       ├── api/                  axios 实例、令牌与 X-Tenant-ID、错误归一；各领域接口函数与类型
│       ├── stores/               auth（当前用户、entries）、tenant（当前企业与切换）、ui 偏好
│       ├── composables/          权限判断、分页、上传、SSE、主题等 hooks
│       ├── components/           两个应用都用到的组件（登录表单、扫码登录、企业切换器、布局骨架、空状态、错误页、
│       │                         文档预览、Markdown 渲染、智能体编辑器、知识库编辑器、IM 渠道面板……）
│       ├── directives/、utils/、types/
│       ├── i18n/                 createAppI18n() 与公共文案；应用文案由各应用合并
│       └── styles/               设计令牌、TDesign 主题、全局样式
├── workspace/                    @nexus-web/workspace：员工工作台（Vite 应用）
│   ├── index.html                工作台入口（含单智能体模式路由 /agents/:agentId/chat）
│   ├── embed.html                对外嵌入页入口（第二个 Vite 入口）
│   └── src/
└── admin/                        @nexus-web/admin：企业管理后台（Vite 应用，base 为 /admin/）
    ├── index.html
    └── src/
```

智能体编辑器与知识库编辑器放在 `core`：工作台用它编辑个人资源，管理后台用它编辑企业资源；组件按接口返回的 `can_maintain`、`ownership` 决定哪些控件可用，不在组件内推断权限。

### 4.2 依赖规则

- `core` 不得导入 `workspace` 或 `admin`；两个应用互不导入。由 `apps/web/scripts/check-boundaries.test.ts` 扫描 import 路径。
- 只有两个应用都用到的代码，或者属于平台基础能力（请求层、认证、企业切换、权限、主题、i18n）的代码，才放进 `core`。
- 接口函数与类型统一放在 `core/src/api`。
- 依赖版本用 `catalog:` 统一；`core` 以 peerDependencies 声明 Vue、TDesign、pinia、vue-router、vue-i18n，避免出现两份实例。
- `core` 以源码形式被引用（`"@nexus-web/core": "workspace:*"`），由各应用的 Vite 编译，并排除在依赖预构建之外。

### 4.3 两个应用

| | 员工工作台 `workspace` | 企业管理后台 `admin` |
|---|---|---|
| 面向 | 企业全体员工 | 有治理权限的企业成员 |
| 形态 | 桌面与手机 | 只做桌面 |
| 部署路径 | `/`；单智能体模式 `/agents/:agentId/chat`；嵌入页 `/embed/:channelId` | `/admin/` |
| 企微应用用途 | `workspace`、`agent` | `admin` |
| 进入条件 | `entries.workspace`；单智能体模式另需该智能体的使用权 | `entries.admin`；不满足时显示无权限页 |

- **单智能体模式**：只显示该智能体的对话（会话列表、对话区、产物），没有其他导航，适合企微里“一个智能体一个应用”的场景。
- 登录页（邮箱密码、企微扫码）与改密页来自 `core`。默认同域名部署，两个应用共用登录状态。
- `/auth/me` 增加 `entries`：`workspace`（当前企业的有效成员）、`admin`（持有任一治理权限，或是 owner、admin）。路由守卫只读取 `entries`。
- 管理类接口统一加前缀 `/api/v1/tenants/{id}/admin/...`，旧路径保留一个版本周期；权限判断在每个接口内。

### 4.4 命令、构建与部署

| 命令（在 `apps/web/` 执行） | 作用 |
|---|---|
| `pnpm install --frozen-lockfile` | 安装三个项目的依赖 |
| `pnpm dev:workspace` | 工作台开发服务（5173，`/api` 代理到 API） |
| `pnpm dev:admin` | 管理后台开发服务（5174，base `/admin/`） |
| `pnpm build` | 分别产出 `workspace/dist` 与 `admin/dist` |
| `pnpm type-check`、`pnpm test`、`pnpm test:browser` | 类型检查、单元测试与边界检查、两个应用的浏览器测试 |

部署：反向代理把 `/admin/` 指向 `admin/dist`，`/embed/` 指向 `workspace/dist/embed.html`，`/wecom/` 与 `/api` 指向 API 服务，其余指向 `workspace/dist`。

### 4.5 删除清单

| 删除项 | 位置（现 `apps/web/src`） |
|---|---|
| 平台管理 | `views/system/`、`/platform-admin` 路由与 `requiresSystemAdmin` 守卫、设置中的 `system-global`、`model-catalog`、`runtime-queues`、`platform-api-keys`、`system-audit-log` |
| 助手 | `components/assistant/`、`views/settings/AssistantSettings.vue`、主布局中的助手启动器 |
| Ollama、WeKnora Cloud | `views/settings/OllamaSettings.vue`、`WeKnoraCloudSettings.vue` 与设置项 |
| CLI、Chrome 插件、Claw 技能 | `views/integrations/CliIntegrationLanding.vue`、`ChromeExtensionLanding.vue`、`ClawSkillLanding.vue`、`config/integrations.ts` 中的对应项 |
| WeKnora API Key | `views/integrations/ApiIntegrationSettings.vue` 与集成页的 `api` 项 |
| 集成页 | 整个“集成”页取消：`im` 改为智能体的“渠道”页（保留并改造 `components/IMChannelPanel.vue`），`embed` 并入同一“渠道”页，`mcpserver` 移入工作台个人设置 |
| 本地浏览器连接 | 工具箱 `browserconnection` 项、`BrowserConnectionSettings.vue` |
| 桌面壳 | `src/wailsjs/`、`/auth/auto-setup` 调用 |
| 个人空间 | 注册页的空间类型选择、空间选择页的“创建个人空间” |
| 连带内容 | 以上功能独占的依赖（逐个确认无其他引用后移除）、各语言包中的文案键与测试 |

## 5. 功能清单

状态列：**已有** = 后端与页面都已接通；**E0–E7** = 本提案对应阶段新增或改造；**待实现** = 页面已存在，后端未接通，不在本提案范围。

### 5.1 员工工作台

导航分为“对话”“我的”“企业分配”“个人设置”四组。

| 模块 | 功能 | 状态 |
|---|---|---|
| 登录与企业 | 邮箱密码登录、首次改密；切换企业；接受邀请、凭邀请链接加入、按企业编码申请加入；新建企业 | 已有，E1 去掉个人空间 |
| | 企微内免登（`workspace`、`agent` 用途应用）、企微扫码登录、首次进入自动开户 | E3 |
| 对话 | 流式回复、思考摘要、引用与证据、附件、工具调用过程、本人确认与“本会话允许”、取消与追问、会话分叉、会话管理、本次生成的文件、运行停滞提示、解除阻塞 | 已有 |
| 单智能体模式 | 企微 `agent` 用途应用打开后直接进入该智能体的对话，只显示会话列表、对话区与产物 | E2、E3 |
| 我的智能体（个人） | 创建、编辑、试运行、发布、停用、删除；共享给角色或共享空间（对方只能使用） | 已有，E0 改为只有创建者可维护，E1 受企业策略约束 |
| | 渠道：企微智能机器人（按策略提交审核）、微信扫码绑定、QQ 扫码绑定；查看渠道状态与审核结果 | E4 |
| | 共享给部门、成员 | E5 |
| 我的知识库（个人） | 创建、可见范围（私有 / 全企业）、文档上传与解析、分块与问答编辑、检索测试、Wiki | 已有，E0、E1 改造 |
| 我维护的企业知识库 | 被指定为知识库管理员的企业知识库：维护文档、分块与问答（不能改设置、可见范围、删除） | E0 |
| 企业分配 | 企业分配给我的智能体（只能使用）；全企业可见的知识库与共享空间共享来的知识库（只读检索）；知识搜索；我所在的共享空间 | 已有，E0 改为只读 |
| 我的技能、记忆、产物、自动化 | 安装与提交技能；记忆草稿审核与编辑；产物预览、下载、删除；定时任务 | 已有 |
| 个人设置 | 个人资料、修改密码、企微绑定、语言与主题、技能环境变量、个人 MCP endpoint 令牌 | 已有 |
| | 个人模型与 Key（仅在 `personal_models` 开启时显示） | 已有，E1 受策略约束 |
| | 我的用量（只读） | E6 |

### 5.2 企业管理后台

按所需权限显示菜单。

| 模块 | 功能 | 所需权限 | 状态 |
|---|---|---|---|
| 企业信息 | 名称、编码、描述；删除企业 | owner | 已有 |
| 成员 | 列表、按邮箱添加或邀请、邀请链接、加入申请审批、改角色、移除 | `members:manage` | 已有 |
| 部门架构 | 子公司与部门的维护、成员的部门归属 | `org:manage` | 已有 |
| | 企微同步的部门（只读）与同步状态 | `org:manage` | E3 |
| 角色与权限 | 自定义角色（菜单与 API 权限）、按部门批量分配 | `roles:manage` | 已有 |
| | 内置角色 `security_admin`、`auditor`；新权限 `enterprise_agents:manage`、`enterprise_kbs:manage` | `roles:manage` | E0、E1 |
| 企业策略 | 自建范围、个人模型、外部共享、个人企微机器人（审核 / 开放 / 禁止）、个人微信与 QQ 渠道、留存天数 | `policy:manage` | E1（渠道两项 E4 生效） |
| 企业微信 | 企业绑定（corp_id、通讯录密钥、回调参数）；自建应用列表（用途、agentid、密钥、绑定的智能体、主页地址一键复制、是否用于扫码登录）；通讯录同步 | `org:manage` | E3 |
| 企业智能体 | 创建、编辑、试运行、发布、停用、删除；分配给角色（E5 起含部门、成员）；企微渠道配置 | `enterprise_agents:manage` | E0（复用现有编辑器），E4（渠道） |
| 渠道审核与总览 | 个人企微机器人的待审核列表（通过、驳回）；全企业渠道总览（类型、所属智能体、创建者、状态），可停用任一渠道 | `enterprise_agents:manage` | E4 |
| 企业知识库 | 创建、设置、可见范围、删除、共享到共享空间；指定知识库管理员；维护内容 | `enterprise_kbs:manage` | E0 |
| 个人资源治理 | 全企业的个人智能体与个人知识库清单；查看、停用、删除、转为企业资源 | owner、admin | E0 |
| 模型 | 企业模型供应商与 Key、连接测试、各类型默认模型 | `models:manage` | 已有 |
| 工具与技能 | 内置工具与技能启停、工具风险等级；技能导入与审核；MCP 服务（登记、发现、启用、风险策略、OAuth）；联网搜索、对话历史、企业级记忆开关 | `tools:manage` | 已有 |
| 存储与检索 | 向量库、原文件存储后端、解析引擎、连接测试 | owner、admin | 已有（从设置页移入），E2 补网络出口策略 |
| 共享空间 | 创建与管理、邀请其他企业、成员企业级别 | owner、admin | 已有，E1 受 `external_sharing` 约束 |
| 运行状况 | 结果未知的会话列表与解除 | owner、admin | 已有（接口），E2 补页面 |
| 用量与配额 | 按部门、成员、智能体、模型的用量；三级月度上限 | `models:manage` | E6 |
| 审计 | 查询；查看正文（另需权限并留痕）；导出 | `audit:read`、`audit:read_content` | 已有（查询），E1、E7 |

### 管理界面布局与内容样式

管理端采用与 workspace 一致的主框架、可折叠图标侧栏与左下角账户菜单，具体见 E2.5.10；不提供返回工作台或关闭入口。内容页面继续复用 core 的设置标题、标准设置行、列表工具按钮、表格框和主题，不产生应用间导入。权限、API、表单提交和确认规则保持不变。

### 部门组织界面的当前实现边界

管理端 `/admin/organization` 消费既有 `/org-units` 契约，不新增权限：树、节点及归属操作需要 `org:manage`，全企业成员候选另需 `members:manage`。节点来源为 `wecom` 时界面只读，启用节点下可新增手工子部门；首次归属的主部门标记采用服务器刷新结果。根不可移动/删除，移动排除自身及子树，危险操作确认，切换选择或身份后旧响应与确认失效。

同步部门只读仍是目标要求：通用服务端写接口尚未按来源阻止修改，树 DTO 未暴露混合手工根的同步外部标记，归属 DTO 无同步来源，因此不能由本次界面实现推导出服务端保证。服务端来源保护、可辨识契约及同步配置/状态列入原变更 E2.5.8，完善设计并确认后实施。

### 5.3 对外嵌入页 `/embed/:channelId`

给企业外部访客使用，属于工作台项目的第二个入口，本质上是“绑定一个智能体的渠道”之一，在智能体的“渠道”页配置。前端页面已存在（WeKnora 副本），后端整体为**待实现**，另提案。清单：单个绑定的智能体、流式回复与引用、访客会话保存在浏览器本地、外观由渠道配置、只能绑定无需人工确认的工具、只能读全企业可见的知识库、域名白名单、限流、不写入员工记忆、访客会话属于企业并计入用量与审计。

### 5.4 部署级配置（取消平台管理界面后的去向）

| 原平台管理或设置页中的项 | 去向 | 理由 |
|---|---|---|
| 向量库、存储后端、解析引擎 | 企业管理后台 | 已按企业保存，只影响本企业 |
| 内置向量库与原文件目录（`[knowledge]`） | `configs/nexus.toml` | 宿主机路径 |
| 沙箱档位与隔离验收（`[sandbox]`、`--sandbox-check`） | 配置文件与命令行 | 宿主机安全 |
| 联网搜索后端与密钥（`[web]`） | 配置文件 | 全部署共用 |
| 模型网络出口、连接池、并发与限流 | 配置文件 | 共享资源 |
| 注册开关、认证与主密钥（`[auth]`、`[security]`） | 配置文件与环境变量 | 部署安全 |
| 平台管理员、内置技能导入、全局 unknown 解除 | 命令行（`set-platform-admin`、`import-builtin-skills`、`list-unknown` / `resolve-unknown`） | 已有 |
| 平台概览、跨企业清单 | 删除（3.5） | 平台运维不应看到企业数据 |
| 模型目录、任务队列、平台 API Key、系统审计、系统设置页面 | 删除 | 未接后端的 WeKnora 副本 |
| `[wecom]` | 删除，改为各企业在管理后台配置（第 6 节） | 每家企业自己的企微 |

外部向量库与存储后端的连接复用模型调用的目的地址策略：只允许公网 HTTPS、检查 DNS 解析结果并固定 IP、禁用重定向；私有地址只有列入 `[model_network]` 白名单时才允许。

## 6. E3 企业微信：企业、多应用与登录

### 6.1 数据

```text
tenant_wecom_corps(tenant_id PK, corp_id UNIQUE, contacts_secret_ciphertext, callback_token_ciphertext,
                   encoding_aes_key_ciphertext, sync_status, synced_at, updated_by, updated_at)
tenant_wecom_apps(id PK, tenant_id, wecom_agentid, secret_ciphertext, name,
                  purpose CHECK IN ('workspace','admin','agent'), nexus_agent_id NULL,
                  qr_login BOOL, status, created_by, created_at, updated_at)
  UNIQUE (tenant_id, wecom_agentid)
  UNIQUE (nexus_agent_id) WHERE purpose = 'agent'      -- 一个智能体最多一个应用
  CHECK  ((purpose = 'agent') = (nexus_agent_id IS NOT NULL))
  至多一行 qr_login = true（部分唯一索引）
```

- 字段名用 `wecom_agentid` 表示企微应用的 agentid，`nexus_agent_id` 表示 Nexus 智能体，避免混淆。
- 密钥用现有 Fernet 主密钥加密，不进事件与审计。`purpose = 'agent'` 的应用只能绑定本企业的智能体；该智能体被删除或停用时，应用状态改为 `disabled`。

### 6.2 企微内免登

1. 管理后台为每个应用生成主页地址 `https://<host>/wecom/apps/{app_id}/entry`，管理员把它填到企微应用的“应用主页”。
2. `GET /wecom/apps/{app_id}/entry`：生成一次性 `state`，跳转到企微网页授权（使用该应用的 `wecom_agentid`）。
3. 回调 `GET /wecom/apps/{app_id}/callback?code=&state=`：校验 `state`，用该应用的密钥换取 `userid`，按 `(wecom, corp_id, userid)` 找到账号；未绑定且已同步的成员自动开户（`contributor`）；签发会话，并把当前企业设为该应用所属的企业。
4. 按用途跳转：`workspace` → `/`；`admin` → `/admin/`（无治理权限时显示无权限页）；`agent` → `/agents/{nexus_agent_id}/chat`（无使用权时显示无权限页）。

企微可见范围只决定谁能看到应用，所有权限仍以 Nexus 的判断为准。

### 6.3 扫码登录

- 登录页的“企微扫码”先让用户输入企业编码（或从上次登录记住），找到该企业 `qr_login = true` 的应用，生成扫码登录地址；回调流程与 6.2 第 3 步相同，登录后进入工作台。
- 一个企业没有标记扫码应用时，默认使用第一个 `workspace` 应用；没有任何 `workspace` 应用时，登录页不显示企微扫码。

### 6.4 通讯录同步与离职

- 回调：每企业一个 URL `/api/v1/integrations/wecom/{tenant_id}/callback`，先验签解密，再分发到“通讯录变更”与“消息”（E4）。
- 同步顺序：部门 → 成员 → 主部门 → 停用差集；每天全量一次，加上回调增量。
- 离职：成员被删除或移出同步范围时，把 `tenant_memberships.status` 设为 `revoked` 并写入审计；资产不动。
- `WeComDirectory` 协议按企业、按应用构造实例（凭据来自上述两表），HTTP 实现放在 `connectors/wecom`，platform 只依赖协议。
- 实施前（E3.0）核对企微官方文档：自建应用网页授权与扫码登录的参数、通讯录读取所需的密钥与可读范围（通讯录同步密钥与应用密钥各自能读到哪些字段，是否只限应用可见范围）、成员姓名等敏感字段的获取条件、回调验签方式。结果记入本节；字段缺失时降级为“只用 userid，姓名由员工首次登录时补全”。
- 核对结果（2026-11-12，官方文档 90200、90208、90968）：`/cgi-bin/user/simplelist` 与 `/cgi-bin/department/list` 只返回调用应用可见范围内的数据，名称字段须管理员授权才返回；2022-08-15 起通讯录同步助手配置的新 IP 不能再调用这两个读取接口，因此同步改用自建应用自己的密钥；回调签名为 `sha1(sort(token, timestamp, nonce, msg_encrypt))`，`AESKey = base64(EncodingAESKey + "=")`、AES-256-CBC、IV 取密钥前 16 字节、PKCS#7 补齐到 32 字节，明文为 16 字节随机串、4 字节网络序长度、消息与 corpid。

## 7. E4 IM 渠道

参考实现：WeKnora `internal/im/`（`wecom/ws_adapter.go` 企微智能机器人长连接、`wechat/` iLink 扫码与长轮询、`qqbot/` QQ 官方机器人、`service.go` 与 `qaqueue.go` 的会话与排队、`channel_security.go`）；octop-gateway `channels/weixin/`、`channels/qq/`（含 `login_qr.py` 扫码绑定）、`manager.py`（按会话合批）、`constraints.py`（平台限制与限流）；deer-flow `app/channels/`（`wechat_qr_login.py`、`leadership.py` 连接归属）。实施前按 `AGENTS.md` 比较这些实现后选型。

### 7.1 数据

```text
agent_channels(id PK, tenant_id, agent_id, kind CHECK IN ('wecom_bot','wecom_app','wechat','qq'),
               owner_user_id,            -- 创建渠道的人；微信、QQ 渠道的唯一对话者
               config_ciphertext,        -- wecom_bot：bot id 与 secret；wechat：iLink token 与 bot 账号；
                                         -- qq：AppID 与 AppSecret；wecom_app：引用 tenant_wecom_apps.id
               bound_external_id NULL,   -- 微信、QQ：绑定者在该平台的用户 id（认领后写入）
               claim_code_hash NULL,     -- QQ：首次对话的绑定码（一次性、限时）
               status CHECK IN ('pending_review','active','rejected','disabled','expired'),
               reviewed_by NULL, reviewed_at NULL, review_note NULL,
               lease_owner NULL, lease_until NULL,   -- 长连接 / 长轮询的持有者
               created_at, updated_at)
channel_identities / channel_session_bindings：沿用架构 2.14 的 ChannelIdentity、ChannelSessionBinding，
  会话键为 (channel_id, 平台会话 id, user_id)
```

### 7.2 创建与状态

| 渠道 | 谁能创建 | 初始状态 |
|---|---|---|
| `wecom_bot`、`wecom_app`（企业智能体） | `enterprise_agents:manage` | `active` |
| `wecom_bot`（个人智能体） | 智能体创建者 | `personal_wecom_channels`：`review` → `pending_review`；`open` → `active`；`disabled` → 拒绝创建 |
| `wechat`、`qq`（个人智能体） | 智能体创建者 | `personal_external_channels = true` 时，扫码或认领完成后为 `active`；否则拒绝创建 |

- 审核：管理后台“渠道审核”列出 `pending_review`，可以查看智能体（只读）、渠道配置（不含密钥），然后通过或驳回（填写原因）。通过、驳回、停用都写入审计并通知创建者（工作台消息）。
- 策略收紧时（例如改为 `disabled`、关闭 `personal_external_channels`），已启用的对应渠道转为 `disabled`。
- 微信 iLink 令牌失效时转为 `expired`，在渠道页提示重新扫码。
- 智能体停用或删除、渠道创建者离职（成员身份撤销）时，渠道转为 `disabled`。

### 7.3 连接管理

- worker 内新增渠道连接管理器：周期性领取 `active` 且租约过期的渠道（`lease_owner`、`lease_until`，与 Run 租约同一模式），为每个渠道维持一个长连接（企微智能机器人 WebSocket、QQ 网关 WebSocket）或长轮询（微信 iLink）；续租失败立即断开，保证同一渠道同一时刻只有一个持有者。
- 每个 worker 的渠道连接数上限由 `[channels].max_connections_per_worker` 配置；重连使用指数退避与抖动。
- 网络出口：只允许连接各平台的固定域名（企微、iLink、QQ），不经过模型出口白名单的私有地址例外。

### 7.4 消息处理

1. 收到消息，按平台消息 id 去重。
2. 确定身份：
   - 企微渠道：发送者 `userid` → `(wecom, corp_id, userid)` → Nexus 成员；找不到或已离职回复“未开通”；
   - 微信、QQ 渠道：发送者必须等于 `bound_external_id`，否则不处理；QQ 渠道未认领时，只接受绑定码消息，校验通过后写入 `bound_external_id`；身份即 `owner_user_id`。
3. 检查 `can_use_agent`（个人智能体的创建者总是满足），以及渠道状态为 `active`、所属企业策略仍允许。
4. 找到或创建（渠道、会话、成员）的会话，以该成员身份提交 Run（与工作台相同的准入、预算、授权与审计）。
5. 流式结果按平台限制合并后回复；超长内容截断并附工作台链接。需要人工确认的工具调用，回复“请到工作台确认”并附链接。
6. 只在平台明确拒绝时重试投递。

实施前（E4.0）核对：企微智能机器人长连接的协议与限流、单聊与群聊 @ 的消息格式；腾讯 iLink Bot 接口的扫码流程、令牌有效期与使用条款；QQ 官方机器人对个人开发者的开放范围、扫码创建绑定流程、私聊（C2C）的主动与被动回复限制。结论记入本节；某个平台条件不满足时，该渠道标记为 `unverified`，不在界面上提供。

## 8. E5–E7（要点）

- **E5**：新增 `agent_principal_grants(tenant_id, agent_id, principal_kind, principal_id, include_descendants)`（只授予使用），`principal_kind` 取 `org_unit` 或 `user`；知识库可见范围增加按部门、成员开放；知识库管理员可按部门、角色指定（已确认，E5 实施）。部门展开用递归 CTE，每个请求内缓存一次。
- **E6**：`usage_ledger(tenant_id, user_id, org_unit_id, agent_id, channel_id, model_version_id, day, input, output, cache_read, cache_creation)` 从 `usage.updated` 累加；准入时检查企业、部门、个人三级的月度上限，超出返回 429 `quota_exhausted`。
- **E7**：worker 每天按 `retention_days` 清理会话、运行事件与产物；审计按日导出为 JSONL，并写入哈希链字段。

## 9. 多租户隔离的后续加固（不在本提案实施）

- PostgreSQL RLS：以 `app.tenant_id` 会话变量为条件，作为应用层隔离之外的第二道防线。
- 按企业单独设定并发与速率上限，随平台运营另提。

### E2.5.10 管理端主框架对齐 workspace（2026-11-14 已确认）

- 以 `workspace/src/components/menu.vue` 和 `UserMenu.vue` 为直接视觉与交互基线，对齐侧栏尺寸、背景、品牌区、菜单间距、激活态、折叠按钮及底部用户区；本方案取代主框架沿用设置页外壳的设计。内容区保留现有设置组件与业务页面。
- admin 不导入 workspace。比较固定版本 WeKnora `e1f9a6166` 与当前 workspace 的 menu.vue 后，沿用当前 workspace 的视觉栅格。工作台菜单及账户组件耦合会话、邀请与资源状态，管理端只需四项治理导航，因此外壳和账户编排保留在 AdminLayout；复用 core 的认证、主题、图标及类型化 API，不新增无实际消费者的公共壳组件。
- 展开时展示菜单图标和文字、账户头像及可读身份与企业名；折叠时保留图标、头像、可访问名称和提示。账户入口固定侧栏底部，菜单超长时独立滚动，用户入口不随菜单滚走。
- 企业切换迁入底部用户菜单，使用当前 memberships 和既有切换逻辑。切换期间阻止重复操作、作废旧 context，重新获取身份与权限并返回概览；失败提供反馈。保留退出操作，移除当前外壳的关闭/返回工作台入口；admin 与 workspace 为两个独立应用，管理端主框架不提供返回工作台操作。无管理权限时维持拒绝访问状态。
- 折叠偏好采用 admin 独立本地键，避免与工作台宽度及状态互相覆盖；侧栏和内容区分别约束滚动，窄窗口保证折叠入口、用户菜单和企业选择可操作。
- 折叠与账户按钮支持键盘、可见焦点、aria-label/aria-expanded；用户弹层支持 Escape 和外部点击关闭，关闭后焦点回到触发入口。图标继续使用本地可用资源。
- 验证涵盖折叠/展开、路由高亮、权限菜单、底部用户菜单、企业切换成功与失败、退出、过期响应隔离；运行类型检查、相关测试及双应用构建，并在浏览器检查桌面/窄窗口、明暗主题和键盘操作。构建或真实 API 验收受限时据实记录。

### E2.5.3 企业信息迁移批

在已确认的 E2 管理业务迁移范围内，新增 `/admin/enterprise`，导航和页面仅向当前企业 owner 开放。参考固定版本 WeKnora `TenantInfo.vue` 的设置行、内联编辑、删除危险区和企业名确认；沿用 Nexus 现有 GET/PATCH `/tenants/current` 和 DELETE `/tenants/{id}`，不变更 API、权限或数据模型。现有 PATCH 服务端允许 owner/admin，页面遵循本提案 owner 范围，最终授权仍由服务端复核。

名称限制 1–160 字符、描述不超过 500 字符，与服务端一致；仅提交变化字段，空描述明确清除。详情响应运行时校验类型及企业 ID。保存成功更新当前企业可读名称和成员身份列表；作用域和权限代次变化清空快照、草稿及删除确认，迟到响应不得写入新作用域。读取/保存/删除失败分别保留可重试反馈；删除确认输入当前企业名称，提交中禁止关闭和重复操作。删除成功清除本地身份与管理上下文，在 admin 内进入登录页，不跳转工作台。

现有 TenantView 没有企业编码字段，本批不把 UUID 当编码，也不新增未经确认的契约。企业编码展示/修改、工作台旧企业管理页面清理继续留在 E2.5.3 后续，接口变化需先完善原变更设计并确认。本批不实现退出企业或角色管理。

### E2.5.3 角色与权限迁移批

在已确认的管理业务迁移范围内，新增 `/admin/roles`，以服务端 `roles:manage` 控制导航与页面。对照固定版本 WeKnora `OrganizationSettingsModal.vue` 的成员列表、角色选择及授权确认交互；其组织级角色与 Nexus 企业自定义授权模型不同，因此复用列表与表单组织方式，按 Nexus 现有 roles HTTP/service 实现：权限目录、当前操作者权限、角色列表、自定义角色创建/权限替换、成员角色分配与撤销。无角色删除/改名接口，不提供此类操作；内置角色只读可分配，菜单及 API 授权不得超出操作者已有权限，最终仍由服务端复核。

角色目录与当前授权读取成功前禁止写入，不把读取失败当空权限。成员候选通过现有活跃成员接口按名称展示，需要额外 `members:manage`；无该权限仍可管理角色，成员授权区显示不可用原因，不允许手填 ID。owner 已有全部权限，不作为新增分配候选。角色和成员授权写入前确认；写入后刷新身份与权限，防止撤销自身管理权后继续操作。切换企业/账号/权限代次、刷新和卸载时清空表单及确认，迟到请求不得更新新作用域。写入失败保留草稿，明确反馈；写入成功后权限刷新失败不误报原写入失败。

本批不改后端契约、权限模型，不含角色到智能体的授权、部门批量分配及工作台旧管理代码清理；这些仍在原变更后续任务中推进。

### E2.5.3.5 部门批量角色分配（已确认）

#### 现状与修复边界

现有 POST `/api/v1/tenants/{tenant_id}/org-units/{unit_id}/role-assignments` 输入 `{ role_id }`，返回 `{ assigned: user_id[], skipped: user_id[] }`。服务调用 `membership._manager` 检查成员管理权限，在锁定企业后检查启用部门与同企业角色，再为直接关联的活跃非 owner 成员添加角色，跳过已有分配。与 `roles.assign_role` 不同，它没有角色管理权限及授予范围校验。

修复复用角色服务的授权原则：调用者同时具有 `members:manage` 和 `roles:manage`，且目标角色 menus/apis 均为当前有效授权的子集。校验在同一写事务、企业锁内，且在任何成员分配写入之前完成。应复用已有角色授权校验职责，避免两套规则随时间分叉；必要的包内公共辅助函数说明用途与约束，不泄漏到 core。保留跨企业角色/部门不可访问、停用部门拒绝、owner 跳过、已有角色跳过、全事务和审计行为。内置角色与单成员分配一致：满足授权子集条件时可分配。

#### 页面交互

角色页增加独立的部门分配区，复用 `organizationRows` 的完整路径区分同名部门，组织树仅在具有 `org:manage` 时读取。已有 `roles:manage`、`members:manage` 及当前角色数据成功读取后，才允许按启用部门和自身可授予角色选择；组织读取失败单独反馈，不阻断角色维护与单成员分配。不允许手填内部 ID。

明确提示“仅当前部门直接成员，不含下级；本次分配不会随未来部门成员变动自动更新”。确认展示部门路径和角色名称；不用 `member_count` 冒充实际新增人数，执行完成按服务端 assigned/skipped 数组显示新增/已分配跳过数量，owner 排除不计入这两个数量。空部门和重复提交都以服务端结果反馈；写入失败保留选择并允许重试。复用既有授权写入后的身份校准，避免自身因新角色而进入过期权限状态；确认及迟到结果受企业、账号与权限代次隔离。

#### 验证

后端覆盖仅有成员管理权限的拒绝、缺少成员管理权限的拒绝、角色管理者不能授予超出自身权限、同等/子集权限成功、直接成员范围不含子部门、owner 跳过、重复幂等、跨企业/停用节点拒绝、403 无部分写入及审计。前端覆盖树读取失败与权限缺失禁用、同名路径、停用部门、角色候选范围、确认失效、请求隔离、结果计数及身份重读；执行相关测试、类型检查、构建与模拟/真实 API 浏览器验证并如实记录限制。

### E2.5.3.5 角色到企业智能体使用授权（已确认）

在角色页新增独立的企业智能体授权区，消费既有 GET `/tenants/{id}/agents`、GET `/agent-grants` 与 PUT `/roles/{role}/agents/{agent}`。仅提供 `view`、`run`，空数组撤销该角色在该智能体上的授权；PUT 整体替换且事前确认，不提供 edit/publish/manage。角色与资源名称来自真实查询，不手填 ID。

候选仅取现有列表返回的 enterprise 资源。此列表受可见性、发布状态及模型权限过滤，明确提示不是完整企业资源目录；不把 can_maintain=false 的治理可见性当作使用授权，实际每项可授予权限由现有服务端检查，拒绝时保留草稿。可见但无使用授权的操作不会绕过服务端校验。无法在当前候选解析名称的已有授权明确提示数量，不冒充零授权或清理未知数据。内置角色的菜单/API 不可编辑不代表不能分配智能体使用授权，沿用原服务端行为。

智能体区的加载、失败和重试独立于角色/成员/部门区；选中角色与智能体时读取其既有 view/run，变更后确认并整体替换，提交空数组须明确显示为撤销。撤销仅影响所选角色，其他角色或部门/成员授权仍可能让使用者保留访问。企业、账号、权限代次变化使选择、草稿、确认及迟到请求失效；复用现有写入后身份校准，成功后的刷新失败单独反馈。工作台旧管理代码隔离和完整企业资源管理仍留后续任务。

### E2.5.3.5.6 工作台旧部门管理清理批

已确认的管理业务迁移收尾中，先移除工作台 `OrgStructure.vue` 及设置导航中的部门管理项；admin 的组织页面已提供对应节点和归属流程。旧 `?section=org-structure` 和内部旧快捷调用保留迁移说明，不再加载组织树或提供写操作；有服务端 admin 入口时提供显式链接进入独立管理应用，无入口显示权限说明，不自动跨应用导航。开发链接使用同主机 5174，生产使用应用 base 下的 admin/organization；admin 继续自己校准身份及 org:manage 权限。

旧 TenantInfo 的退出企业与 TenantMembers 的审计入口尚未完整迁移，本批不删除它们，不宣称工作台已完全隔离管理代码。保留共享空间/组织页面、加入企业、企业切换及个人设置；后续补齐退出/审计承接再清理其余旧页。

### E2.5.3 审计日志迁移批

在已确认的管理业务迁移范围内，新增 `/admin/audit`，按服务端 `audit:read` 控制导航及页面。参考固定版本 WeKnora `TenantMembers.vue` 的审计时间/操作者/动作/目标/结果及展开详情，按 Nexus 实际返回的 metadata 实现文本详情，不伪造 actor_role、请求路径或正文。现有 GET `/tenants/{id}/audit-log?limit=` 最近优先，limit 1–500，无游标；页面提供 100/500 条读取与已加载范围内筛选，明确并非全量检索。

导出沿用 GET `/tenants/{id}/admin/audit/export?start=&end=`，UTC 自然日含首尾，开始不晚于结束，日期差最多 366 天，与服务端一致。使用认证请求层获取 NDJSON Blob 后本地下载，不把令牌放链接、不跳过服务端 audit:read。导出自带哈希链且服务端记录 audit.exported，不宣称已实现审计正文查看；audit:read_content 不替代当前列表/导出权限。

页面区分列表加载失败、空结果、筛选无匹配、导出失败和无权限，元数据仅通过文本渲染；企业/账号/权限代次变化及卸载清空详情、筛选、列表并作废旧请求和下载，避免跨企业文件交付。写入型审计接口行为不变。旧成员页仍有退出/其他未承接流程，本批不整页删除，完整工作台管理依赖清理继续保留。

### E2.5.3.5.6 个人退出企业与旧企业信息清理批

账户资料页承接当前企业的只读信息和本人退出企业操作。使用 effectiveTenantId 调用现有 GET `/tenants/current`，显示真实名称、描述、当前成员角色及状态/创建时间；不为 owner 判断读取全员名单，也不伪造企业配额。普通活跃成员沿用 POST `/tenants/{id}/leave`，无需成员管理权限。后端禁止任何 owner 直接退出，页面据服务端详情角色与当前身份提示先转移所有权，不延用旧页“多 owner 即可退出”的错误假设。

退出前确认企业名称和失去访问的影响；请求期间阻止关闭和重复提交，失败保留当前选择和错误，成功清除本地身份并在工作台自己的登录页重新登录。企业/账号/角色变化及卸载作废旧读取、确认和迟到结果。删除企业和信息编辑已由 admin 承接，删除旧 `TenantInfo.vue` 与对应导航/测试，旧 tenant 设置链接/快捷调用统一规范到 userprofile，保留账户页现有个人资料和改密流程。不改变后端契约、角色权限或退出规则。

旧成员页尚有待梳理入口，工作台完整管理代码隔离继续保留后续任务。

### E2.5.3.5.6 工作台旧成员管理清理批

核对旧 TenantMembers 的成员列表、邀请/临时密码开户、邀请链接/撤销、基础角色调整/移除、加入申请审批与审计，管理端 MembersPage、JoinRequestsPanel、AuditPage 已承接。原成员列表本身需要 members:manage，不是普通员工可读名册；旧页的静态角色矩阵不作为新的权限事实来源。

删除工作台旧成员治理页及仅由它引用的 JoinApplicationsPanel，移除 members 设置导航和未使用的成员管理快捷阈值；保留 members 旧书签/内部快捷调用的迁移说明，复用旧部门迁移组件，提供显式管理端成员与审计链接，入口按当前企业 entries.admin 显示，具体权限由 admin 校准。不自动跨应用跳转，不加载成员/邀请/申请/审计接口。保留共享空间、加入企业、个人邀请、账号成员身份和退出企业，以及仍被其他模块使用的 API 与角色/审计翻译。

此批完成两个旧治理页的收尾，不代表模型、工具、存储等管理配置均迁移，也不提前宣称工作台生产产物已隔离所有管理代码；相关功能及完整构建门禁继续保留。


### E2.3 / E2.5 企业智能体管理实施细节

沿用已确认的企业资源管理范围，抽取现有 Nexus 完整智能体编辑器及其技能面板、表单辅助到 core，工作台与管理端分别组合，不互相导入。默认个人创建保持原接口；管理端显式 enterprise scope 使用现有 POST /tenants/{id}/admin/agents，编辑、发布和归档沿用既有接口，不修改后端契约。模型设置导航通过事件交给应用；后台模型管理尚未迁移时明确提示。知识库候选按现有服务端 DTO 类型校验，企业仅显示企业库；保留未列出旧绑定，不因候选不可见而清空。

后台 /agents 按 enterprise_agents:manage 提供导航与页面，列表仅显示当前企业可见 enterprise 记录，说明发布状态/模型可见性过滤；不声称完整目录。创建/编辑保留模型、提示词、工具、技能、知识库和沙箱配置，保存草稿后发布；发布失败保留草稿并允许更新重试，不能重复创建。归档确认说明停止新运行、保留已有会话；无后端契约的独立停用/恢复不实现。角色使用分配沿用 /roles，部门/成员受众、渠道、试运行等保持后续。

企业、账号、权限变化及卸载使列表、编辑器、确认与迟到结果失效；编辑器加载、技能/知识库查询、工具操作及保存发布链均固定请求企业，切换后不得继续旧链发布。加载失败与空结果分开，禁止加载失败时保存。


### E2.5 企业知识库目录与管理员指定批

沿用已确认的企业知识库管理范围，本批在 /knowledge 提供当前企业可见的 enterprise 知识库目录和知识库管理员分配，不改变后端契约。目录使用 GET /tenants/{id}/knowledge/bases，排除个人库和其他企业共享来的库，明确结果受现有可见性检查影响。类型、可见范围和文档数来自原生 DTO，不使用丢失 ownership 的旧展示适配器。

管理员列表与指定/撤销沿用 /admin/knowledge/bases/{kb}/maintainers。enterprise_kbs:manage 控制页面，资源 can_manage 控制目标，members:manage 仅决定能否读取成员名单并提供新增选择；没有成员管理权限时仍可读取管理员及撤销，不要求输入内部 ID。候选来自当前企业活跃成员，已有管理员不重复添加。确认说明只授予内容维护，不授予设置、可见范围、删除或共享管理权；撤销不覆盖其他已有授权来源。

目录、管理员及成员查询分别呈现加载/失败/空状态。切换目标、企业、账号、权限变化和卸载使旧查询、确认和写入结果失效；写入期间禁止重复提交，列表重读失败不得把已成功写入报告为写入失败。沿用后台现有表格/卡片/图标与窄屏样式。完整知识库编辑器依赖模型、存储、解析、图谱、共享、数据源等组件，已迁入 core；企业创建、设置和受众沿用原生接口。内容页按文档/FAQ/Wiki 类型维护既有内容契约，Wiki 版本冲突需重新加载后再编辑，索引/日志系统页只读；删除/共享治理仍由同一变更后续任务处理。

### E2.3 / E2.5 完整知识库编辑器迁移批

将现有完整编辑器及模型选择、解析/存储/向量库/分块/图谱/图片流水线/共享/数据源/活动记录等实际依赖迁入 core，工作台原入口保留薄组合壳，传入企业与设置导航事件，不把 workspace UI store 搬进公共包。子组件通过注入的宿主导航调用模型、解析和存储设置；后台未迁移的设置目的地明确提示，不跳入员工应用。共用指引、纯辅助与展示组件使用同一实现，不复制业务实现。

企业创建调用既有 /admin/knowledge/bases，个人默认调用原创建接口；编辑沿用原 PATCH。完整 buildSubmitData 转换后合并加载时的原生 settings 快照，分块设置合并未知键，一次提交模型/分块与扩展配置，避免旧两段保存导致后段整体替换 settings 丢失配置及部分成功。已有库类型、存储后端和向量库绑定按服务端不可变约束显示只读；不改变后端契约。编辑前校验目标企业、can_manage 和管理员应用要求的 enterprise 归属。可见范围沿用原生 private/tenant；企业目录的受众面板调用现有整体替换接口设置 scoped 的成员/部门范围，新建仍不生成没有受众的 scoped 库。受众选择需分别读取成员与组织目录，缺少目录权限或读取失败时保留对应既有项并禁用该类编辑。服务端负责校验租户成员/部门以及已绑定智能体影响（`kb_in_use`）；清空范围不自动扩大可见性，设置页可显式恢复 tenant/private 后再清理失效受众记录。创建成功保留 ID 继续后续配置，读取失败允许重读同一记录，不能重试创建出副本。

身份/企业/目标/权限与卸载作废旧加载、确认、写入结果和后续请求；保存、描述生成、重建、受众设置等异步链固定企业，提交期间禁止重复写入与关闭。能力目录与共用缓存清理作用域，子面板按身份与目标重挂，不向新企业续发旧链。完整迁移保留现有功能与待实现能力标记，企业内容页面/删除治理仍在原变更后续。完整类型、构建及真实 API 浏览器验收不足继续保留 E2.8。
