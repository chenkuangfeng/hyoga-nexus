# 设计

本文件写 E0–E2 的设计、前端入口的功能清单与部署级配置的去向，以及 E3–E6 的要点。各阶段开始前补齐接口与表结构，并经用户确认。

## 1. 租户模型

```text
部署（共享数据库、共享表，按 tenant_id 隔离）
  ├─ 企业 A（tenants.kind = 'enterprise'）
  │    ├─ enterprise_policies、tenant_wecom_apps
  │    ├─ 组织树（org_units / user_org_units，source = manual | wecom）
  │    ├─ 成员（tenant_memberships，source 增加 wecom）与角色（含 security_admin、auditor）
  │    ├─ 企业共享资源：可见范围为 tenant（以及 E4 的部门、成员）的智能体、知识库……
  │    └─ 每个成员的个人区：本人的会话、记忆、私有智能体、私有知识库、产物
  ├─ 企业 B（只有一个成员，与企业 A 没有任何区别）
  └─ 共享空间（跨企业协作，受各企业的 external_sharing 约束）
```

- **多租户方式**：共享库、共享表，用行级的 `tenant_id` 隔离。所有业务表都带 `tenant_id`，并用复合外键保证引用不跨企业（沿用 `org_units`、`tenant_agent_grants` 的做法）。PostgreSQL 行级安全（RLS）作为纵深防御，暂不启用，见第 7 节。
- **只收紧**：平台守卫 ⊇ 企业策略 ⊇ 空间角色与资源授权。企业策略不能放宽平台已有的检查。
- **执行时复核**：策略、组织关系、成员状态在每次请求和每次工具调用时重新查询，不进入 Run 快照。

## 2. E0 知识库维护开放给智能体管理员

`packages/platform/src/nexus_platform/knowledge/access.py`：

```python
def can_maintain_content(db, kb, user_id) -> bool:
    """文档级维护：can_write 成立，或者调用者管理着一个绑定了该库的本企业智能体。"""
```

- 判断条件：`kb.status == 'active'`；调用者是 `kb.tenant_id` 的有效成员；存在 `agent`，满足 `agent.tenant_id == kb.tenant_id`、`agent_permissions(...)` 含 `manage`、草稿绑定或当前已发布版本的绑定中有 `kind = 'knowledge_base'` 且 `resource_id = kb.id`。
- 每次请求现查，不缓存。解除绑定或撤销 `manage` 后，下一次请求即失去权限。
- 接入点：文档上传、删除、重新解析，分块与问答的增删改走 `can_maintain_content`；库的设置、删除、共享、存储与解析器配置仍走 `can_write`。
- 可读性：E1 引入私有库之后，`can_read` 对满足上述条件的调用者同样放行，否则维护者看不到要维护的库。
- 审计：通过这条路径写入的操作，在审计 detail 中记录 `via_agent_id`。
- 接口返回 `can_maintain` 字段，前端据此显示维护入口，不自行推断。

## 3. E1 租户与个人区

### 3.1 注册即创建企业

- `kind` 的取值按需要确认的项 2 处理；不增加套餐或试用字段。
- `auth/accounts.py` `register`：去掉 `space_kind` 参数，一律创建企业。企业名称选填，不填时生成“{显示名}的企业”；企业编码选填，不填时生成随机编码（仍然全局唯一）。
- 注册页去掉“个人 / 企业”的选择，企业名称与编码作为选填项。
- 登录：默认进入 `last_active_tenant_id`，没有时进入最早加入的企业（不再“个人空间优先”）。`onboarding/workspace` 页面去掉“创建个人空间”。

### 3.2 私有知识库

- 迁移：`knowledge_bases.visibility`（`private`、`tenant`，非空；已有知识库设为 `tenant`）。
- `can_read`：`kb.tenant_id == tenant_id` 时，`tenant` 可见范围对全体成员放行；`private` 只对创建者、企业 owner 与 admin、满足 `can_maintain_content` 的人放行。共享到共享空间的路径不变，但只有 `tenant` 可见范围的库才能共享出去。
- 修改可见范围属于 `can_write`。从 `tenant` 改为 `private` 时，如果有其他人可用的智能体绑定了这个库，就拒绝修改（409 `kb_in_use`），并列出这些智能体。
- 智能体发布检查（`agents/service.py` 发布时的绑定校验）：智能体有除创建者以外的使用者（角色授权、E4 的部门或成员授权、共享空间共享）时，所绑定的知识库必须是 `tenant` 可见范围（E4 之后为“覆盖使用范围”），否则返回 422 `binding_scope_narrower`。

### 3.3 企业策略

`enterprise_policies(tenant_id PK, self_build_agents, self_build_org_unit_ids JSON, personal_models, external_sharing, retention_days, updated_by, updated_at)`；企业创建时写入默认行。

- 读取接口对所有成员开放（前端据此隐藏入口），修改需要 `policy:manage`。
- 检查点：
  - 创建智能体：检查 `self_build_agents`，`org_units` 模式按调用者当前所在部门（含祖先）匹配；企业 owner、admin 不受限制；
  - 模型选择、发布与 Run 准备：`personal_models = false` 时，个人模型（`owner_user_id` 非空）既不能选择，也不能执行；
  - 共享到共享空间：检查 `external_sharing`。共享空间里只要有其他企业的成员租户就算外部。

### 3.4 企业级管理角色

- `authz/catalog.py` 增加 `policy:manage`、`audit:read_content`，二者纳入 `GOVERNANCE_APIS`。
- `tenant_roles.builtin`（布尔）。企业创建时写入 `security_admin`（`policy:manage`、`tools:manage`、`audit:read`）和 `auditor`（`audit:read`）；已有企业由迁移补齐。内置角色不能删除、不能改名，可以分配给成员。
- 审计正文：只有 `audit:read_content` 才能看到对话正文与工具参数，每次查看本身也写入审计。

### 3.5 PostgreSQL 门禁

路线图 2.9 的全部项目，加上本提案新增的列与表，在 PostgreSQL 上完成迁移往返和并发测试后，E1 才算验收。

## 4. 前端入口与功能清单

### 4.1 入口一览

| 入口 | 面向 | 形态 | 本提案 |
|---|---|---|---|
| 员工工作台 `/workspace` | 企业全体员工；企微 H5 打开的就是它 | 桌面与手机 | E2 拆分 |
| 企业管理后台 `/admin` | 有治理权限的企业成员 | 只做桌面 | E2 拆分 |
| 对外嵌入页 `/embed/:channelId`（`embed.html`） | 企业外部访客 | 嵌入第三方网页，桌面与手机 | 只列清单，后端另提案 |
| ~~平台管理 `/platform-admin`~~ | — | — | E2 删除；部署级配置改由配置文件与命令行管理，见 4.4 |

状态列的含义：**已有** = 后端与页面都已接通；**E0–E6** = 本提案对应阶段新增或改造；**待实现** = 页面已存在（WeKnora 副本或占位），Nexus 后端尚未接通，不在本提案范围。

### 4.2 员工工作台 `/workspace`

导航分为“对话”“我的”“企业共享”“个人设置”四组。

| 模块 | 功能 | 状态 |
|---|---|---|
| 登录与企业 | 邮箱密码登录、首次改密 | 已有 |
| | 企微扫码登录、企微内免登、首次进入自动开户 | E3 |
| | 切换企业；接受邀请、凭邀请链接加入、按企业编码申请加入 | 已有 |
| | 新建企业（注册人成为 owner） | 已有，E1 去掉个人空间 |
| 对话 | 新建会话（选择可用智能体）、流式回复、思考摘要、引用与证据查看 | 已有 |
| | 附件上传、工具调用过程展示、工具执行前本人确认、“本会话允许”的放行与撤销 | 已有 |
| | 取消、继续、追问；会话分叉；会话列表、搜索、重命名、删除 | 已有 |
| | 本次生成的文件卡片（预览、下载）；运行停滞提示与“继续等待”；结果未知的会话解除阻塞 | 已有 |
| | 在企微里与智能体对话（消息渠道） | E3 |
| 我的智能体 | 创建、编辑（提示词、模型、工具组、技能、知识库、MCP、记忆开关、沙箱档位）、试运行、发布版本 | 已有，E1 受企业策略约束 |
| | 共享给角色 | 已有 |
| | 共享给部门、成员 | E4 |
| | 共享到共享空间 | 已有，E1 受 `external_sharing` 约束 |
| | 嵌入渠道配置（生成嵌入码、允许的域名） | 待实现 |
| 我的知识库 | 创建、设置可见范围（私有 / 全企业） | E1 |
| | 文档上传、解析、分块与问答编辑、检索测试、知识库 Wiki | 已有 |
| | 维护我管理的智能体所绑定的库 | E0 |
| 我的技能 | 安装技能、提交技能审核、查看审核结果 | 已有 |
| 我的记忆 | 记忆列表、草稿审核（改标题与重要度、看证据与冲突提示）、编辑、删除、个人开关 | 已有 |
| 我的产物 | 列表、筛选、预览、下载、删除（含全部版本） | 已有 |
| 我的自动化 | 定时任务的创建、修改、暂停与恢复、立即运行、运行记录 | 已有 |
| 企业共享 | 企业或部门开放给我的智能体（直接开始对话） | 已有（按角色），E4（按部门、成员） |
| | 全企业可见的知识库、共享空间共享来的知识库（只读检索） | 已有 |
| | 知识搜索（跨我可读的全部知识库） | 已有 |
| | 我所在的共享空间（查看共享来的智能体与知识库） | 已有 |
| 个人设置 | 个人资料、修改密码、企微绑定、界面与助手偏好、技能环境变量 | 已有 |
| | 个人模型与 Key（仅在 `personal_models` 开启时显示） | 已有，E1 受策略约束 |
| | 我的用量（只读） | E5 |
| | 个人 MCP endpoint 令牌（供 Codex、Claude Code 等外部客户端访问平台工具） | 已有 |

### 4.3 企业管理后台 `/admin`

按所需权限显示菜单，持有任一治理权限即可进入（见 4.6）。

| 模块 | 功能 | 所需权限 | 状态 |
|---|---|---|---|
| 企业信息 | 名称、编码、描述；删除企业 | owner | 已有 |
| 成员 | 列表、按邮箱添加或邀请、邀请链接、加入申请审批、改角色、移除 | `members:manage` | 已有 |
| 部门架构 | 子公司与部门的增删改、移动、停用；成员的部门归属 | `org:manage` | 已有 |
| | 企微同步的部门（只读）与同步状态 | `org:manage` | E3 |
| 角色与权限 | 自定义角色（菜单与 API 权限）、按部门批量分配、智能体级授权 | `roles:manage` | 已有 |
| | 内置角色 `security_admin`、`auditor` | `roles:manage` | E1 |
| 企业策略 | 自建范围、个人模型、外部共享、留存天数 | `policy:manage` | E1 |
| 企业微信 | 应用配置（模式、corp_id、密钥、回调）、通讯录同步、消息渠道开关 | `org:manage` | E3 |
| 模型 | 企业模型供应商与 Key、连接测试、各类型默认模型 | `models:manage` | 已有 |
| 工具与技能 | 内置工具与技能的启停、工具风险等级 | `tools:manage` | 已有 |
| | 技能导入、技能提交的审核 | `tools:manage` | 已有 |
| | MCP 服务：登记、发现工具、启用工具、单个工具的风险策略、OAuth 授权 | `tools:manage` | 已有 |
| | 联网搜索、对话历史、企业级记忆开关 | `tools:manage` | 已有 |
| 存储与检索 | 向量库（内置或外部连接）、原文件存储后端、解析引擎配置、连接测试 | owner、admin | 已有（按企业保存，从设置页移入）；E2 补网络出口策略 |
| 智能体治理 | 全企业智能体清单（含私有）、查看配置与版本、停用、删除 | owner、admin | 已有（列表），E2 补停用与删除 |
| 知识库治理 | 全企业知识库清单（含私有）、修改设置与可见范围、共享到共享空间、删除 | owner、admin | 已有（共享），E1 补可见范围 |
| 共享空间 | 创建与管理共享空间、邀请其他企业、成员企业的级别 | owner、admin | 已有，E1 受 `external_sharing` 约束 |
| 运行状况 | 结果未知（unknown）的会话列表与解除 | owner、admin | 已有（接口），E2 补页面 |
| 用量与配额 | 按部门、成员、智能体、模型的用量报表；三级月度上限 | `models:manage` | E5 |
| 审计 | 审计查询（元数据）；查看正文（另需权限并留痕） | `audit:read`、`audit:read_content` | 已有（查询），E1 补正文权限 |
| | 审计导出 | `audit:read` | E6 |

### 4.4 部署级配置（取消平台管理界面后的去向）

不提供 Web 界面。判断标准：配置项一旦改动会影响其他企业或宿主机，就属于部署级；只影响本企业的，放进企业管理后台。

| 原平台管理或设置页中的项 | 去向 | 理由 |
|---|---|---|
| 向量库、存储后端、解析引擎 | 企业管理后台（4.3“存储与检索”） | 已按企业保存（`vector_stores`、`storage_backends` 带 `tenant_id`），只影响本企业 |
| 内置向量库与原文件目录（`[knowledge]`） | `configs/nexus.toml` | 宿主机路径，所有企业共用 |
| 沙箱档位与隔离验收（`[sandbox]`、`--sandbox-check`） | 配置文件与命令行 | 关系到宿主机安全 |
| 联网搜索后端与密钥（`[web]`） | 配置文件 | 全部署共用一份密钥 |
| 模型网络出口、连接池、并发与限流（`[model_network]`、`[model_connection_pool]`、`[worker]`、`[platform]`、`[model_limits]`） | 配置文件 | 共享资源，改动影响所有企业 |
| 注册开关、认证与主密钥（`[auth]`、`[security]`） | 配置文件与环境变量 | 部署安全 |
| 平台管理员 | 命令行 `set-platform-admin` | 已有 |
| 内置技能导入 | 命令行 `import-builtin-skills` | 已有 |
| 结果未知的会话 | 企业管理后台（本企业）；命令行 `list-unknown` / `resolve-unknown`（全部署） | 已有 |
| 平台概览、跨企业清单（`/admin/tenants`、`/admin/summary`、`/admin/agents`、`/admin/sessions`） | 删除 | 平台运维不应通过 Web 看到企业数据 |
| 模型目录、任务队列、平台 API Key、系统审计、系统设置页面 | 删除（均为未接后端的 WeKnora 副本） | 以后做运营台时按需另提 |

### 4.5 对外嵌入页 `/embed/:channelId`

给企业外部访客使用，嵌入在企业自己的网站或页面里。前端页面已存在（`embed.html`，WeKnora 副本），Nexus 尚无嵌入渠道的后端，整体为**待实现**，另提案。清单先固定下来，供那份提案使用：

| 模块 | 功能 |
|---|---|
| 访客对话 | 单个绑定的智能体；流式回复；引用展示；受保护文件的预览 |
| 会话保持 | 访客会话保存在浏览器本地，刷新后继续；不需要登录 |
| 外观 | 标题、头像、欢迎语、推荐问题、主题色（由嵌入渠道配置决定） |
| 安全边界 | 只能绑定无需人工确认的工具；只能读全企业可见的知识库；允许嵌入的域名白名单；按渠道与访客限流；不写入任何员工的记忆 |
| 归属 | 访客会话属于企业，计入企业用量，写入审计；在管理后台可以停用渠道 |

### 4.6 实现要点

- **构建**：`apps/web` 保持一个工程，路由分为 `/workspace/*` 与 `/admin/*` 两棵，各有自己的布局组件。`/admin` 下的页面全部用动态 `import()` 引入，并在 Vite 中配置独立的 chunk 组，员工端首屏不加载管理页面的代码。现有 `/platform/*` 路由重定向到新位置，保留一个版本周期。`embed.html` 仍是独立的 Vite 入口。
- **入口判断**：`/auth/me` 增加 `entries`：
  - `workspace`：当前企业的有效成员；
  - `admin`：当前企业中持有任一治理权限（`members:manage`、`roles:manage`、`org:manage`、`policy:manage`、`audit:read`、`models:manage`、`tools:manage`），或是 owner、admin。
  路由守卫只读取 `entries`。
- **归属表**：`config/settingsAccess.ts` 改为一张表，每一项记录 `entry`（`workspace` 或 `admin`）与所需权限，内容与 4.2–4.3 一致，仍然是前端唯一的依据。
- **网络出口**：外部向量库与存储后端的连接（保存、测试、实际读写）复用模型调用的目的地址策略（只允许公网 HTTPS、检查 DNS 解析结果并固定 IP、禁用重定向），私有地址只有列入 `[model_network]` 白名单时才允许。
- **“我的”与“企业共享”**：由接口字段区分（智能体与知识库的列表接口返回 `owned_by_me`、`visibility`），前端不自行推断。
- **管理接口前缀**：新写的管理接口放在 `/api/v1/tenants/{id}/admin/...`；已有的管理接口在 E2 中迁移，并保留旧路径一个版本周期。

## 5. E3 企业微信（要点）

- `tenant_wecom_apps` 的 `secret` 与 `encoding_aes_key` 用现有 Fernet 主密钥加密，不进事件与审计。
- 回调：每企业一个 URL `/api/v1/integrations/wecom/{tenant_id}/callback`，先验签解密，再分发到“通讯录变更”与“消息”。
- `WeComDirectory` 协议扩展为：部门列表、部门成员详情、成员详情、发送应用消息。HTTP 实现放在 `connectors/wecom`，platform 只依赖协议。
- 同步顺序：部门 → 成员 → 主部门 → 停用差集。
- 自动开户：在 `auth/wecom.py` 的登录分支中，未绑定且 `(corp_id, userid)` 已同步的成员，创建 `users`、`user_identities` 与企业成员身份，不写入 `local_credentials`。
- 离职：同步到成员被删除或移出可见范围时，把 `tenant_memberships.status` 设为 `revoked`，写入审计；资产不动。
- 企微 H5：工作台在企微内置浏览器中使用网页授权免登；手机宽度下的布局纳入 E2 的验收。
- 消息渠道：沿用路线图 9.1 与架构 2.14 的约定（`ChannelIdentity`、`ChannelSessionBinding`、去重、回复长度、只在明确拒绝时重试）。渠道内需要人工确认的工具调用，回复“请到工作台确认”并附链接，不做企微卡片。

## 6. E4–E6（要点）

- **E4**：`tenant_agent_grants` 当前只有 `role_id` 作为接收方。新增 `agent_principal_grants(tenant_id, agent_id, principal_kind, principal_id, permission, include_descendants)`，`principal_kind` 取 `org_unit` 或 `user`；`agent_permissions` 取原有角色授权与新授权的并集。知识库可见范围增加按部门、成员开放。部门展开用递归 CTE 求调用者所在部门的祖先集合，每个请求内缓存一次。
- **E5**：`usage_ledger(tenant_id, user_id, org_unit_id, agent_id, model_version_id, day, input, output, cache_read, cache_creation)` 从 `usage.updated` 累加；准入时检查企业、部门、个人三级的月度上限，超出返回 429 `quota_exhausted`。
- **E6**：worker 每天按 `retention_days` 清理会话、运行事件与产物；审计按日导出为 JSONL，并写入哈希链字段。

## 7. 多租户隔离的后续加固（不在本提案实施）

- PostgreSQL RLS：以 `app.tenant_id` 会话变量为条件，作为应用层隔离之外的第二道防线。
- 每个企业的并发与速率上限：现有的 `max_concurrent_sessions_per_tenant` 已经支持全局统一值，按企业单独设定的上限随平台运营另提。
