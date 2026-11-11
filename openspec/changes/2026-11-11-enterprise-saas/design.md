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

`enterprise_policies(tenant_id PK, self_build_agents, self_build_org_unit_ids JSON, personal_models, external_sharing, retention_days, updated_by, updated_at)`；企业创建时写入默认行。读取对所有成员开放，修改需要 `policy:manage`。检查点：创建个人智能体（`self_build_agents`，企业 owner、admin 不受限）；模型选择、发布与 Run 准备（`personal_models`）；共享到共享空间（`external_sharing`）。

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
| 企业策略 | 自建范围、个人模型、外部共享、留存天数 | `policy:manage` | E1 |
| 企业微信 | 企业绑定（corp_id、通讯录密钥、回调参数）；自建应用列表（用途、agentid、密钥、绑定的智能体、主页地址一键复制、是否用于扫码登录）；通讯录同步 | `org:manage` | E3 |
| 企业智能体 | 创建、编辑、试运行、发布、停用、删除；分配给角色（E5 起含部门、成员）；IM 渠道配置 | `enterprise_agents:manage` | E0（复用现有编辑器），E4（渠道） |
| 企业知识库 | 创建、设置、可见范围、删除、共享到共享空间；指定知识库管理员；维护内容 | `enterprise_kbs:manage` | E0 |
| 个人资源治理 | 全企业的个人智能体与个人知识库清单；查看、停用、删除、转为企业资源 | owner、admin | E0 |
| 模型 | 企业模型供应商与 Key、连接测试、各类型默认模型 | `models:manage` | 已有 |
| 工具与技能 | 内置工具与技能启停、工具风险等级；技能导入与审核；MCP 服务（登记、发现、启用、风险策略、OAuth）；联网搜索、对话历史、企业级记忆开关 | `tools:manage` | 已有 |
| 存储与检索 | 向量库、原文件存储后端、解析引擎、连接测试 | owner、admin | 已有（从设置页移入），E2 补网络出口策略 |
| 共享空间 | 创建与管理、邀请其他企业、成员企业级别 | owner、admin | 已有，E1 受 `external_sharing` 约束 |
| 运行状况 | 结果未知的会话列表与解除 | owner、admin | 已有（接口），E2 补页面 |
| 用量与配额 | 按部门、成员、智能体、模型的用量；三级月度上限 | `models:manage` | E6 |
| 审计 | 查询；查看正文（另需权限并留痕）；导出 | `audit:read`、`audit:read_content` | 已有（查询），E1、E7 |

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

## 7. E4 IM 渠道

### 7.1 数据

```text
agent_channels(id PK, tenant_id, agent_id, kind CHECK IN ('wecom_bot','wecom_app'),
               config_ciphertext, status, created_by, created_at, updated_at)
  wecom_bot：智能机器人的 bot id、回调 token 与 encoding_aes_key
  wecom_app：引用 tenant_wecom_apps.id（purpose = 'agent' 且绑定同一智能体）
channel_identities / channel_session_bindings：沿用架构 2.14 的 ChannelIdentity、ChannelSessionBinding，
  会话键为 (channel_id, 企微会话 id, user_id)
```

- 一个渠道只绑定一个智能体；一个智能体可以有多个渠道。企业智能体的渠道由 `enterprise_agents:manage` 配置；个人智能体能否配置见需要确认的项 2。
- 对外嵌入页将来作为 `kind = 'embed'` 加入同一张表（另提案）。

### 7.2 处理流程

1. 回调验签解密，按消息 id 去重。
2. 发送者 `userid` → `(wecom, corp_id, userid)` → Nexus 成员；找不到或已离职，回复“未开通”。
3. 检查 `can_use_agent`，不满足回复“无权限”。
4. 找到或创建该（渠道、会话、成员）的会话，以该成员身份提交 Run（与工作台相同的准入、预算与授权）。
5. 流式结果按渠道限制合并后回复；超长内容截断并附工作台链接。需要人工确认的工具调用，回复“请到工作台确认”并附链接。
6. 只在企微明确拒绝时重试投递（沿用路线图 9.1 的约定）。

实施前在 E3.0 一并核对企微智能机器人的接收方式（回调或长连接）、单聊与群聊 @ 的消息格式、流式回复能力与频率限制；企微群机器人 Webhook 只能发送，不作为对话渠道。

## 8. E5–E7（要点）

- **E5**：新增 `agent_principal_grants(tenant_id, agent_id, principal_kind, principal_id, include_descendants)`（只授予使用），`principal_kind` 取 `org_unit` 或 `user`；知识库可见范围增加按部门、成员开放；知识库管理员可按部门、角色指定（已确认，E5 实施）。部门展开用递归 CTE，每个请求内缓存一次。
- **E6**：`usage_ledger(tenant_id, user_id, org_unit_id, agent_id, channel_id, model_version_id, day, input, output, cache_read, cache_creation)` 从 `usage.updated` 累加；准入时检查企业、部门、个人三级的月度上限，超出返回 429 `quota_exhausted`。
- **E7**：worker 每天按 `retention_days` 清理会话、运行事件与产物；审计按日导出为 JSONL，并写入哈希链字段。

## 9. 多租户隔离的后续加固（不在本提案实施）

- PostgreSQL RLS：以 `app.tenant_id` 会话变量为条件，作为应用层隔离之外的第二道防线。
- 按企业单独设定并发与速率上限，随平台运营另提。
