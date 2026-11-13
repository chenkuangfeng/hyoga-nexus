# 实施任务

状态：已确认并实施中（2026-11-12）。E0、E1（除 PostgreSQL 门禁）、E3–E7 的后端已完成；E2 前端暂缓；各阶段未完成项与偏离见各节的实施说明。各阶段开始前在 `design.md` 补齐细节并经确认，实施中发现的追加工作写入本文件。

## E0 资源归属与维护权

- [x] E0.1 迁移：`agents.ownership`、`knowledge_bases.ownership`（现有数据设为 `enterprise`）；`knowledge_base_maintainers`；`tenant_agent_grants` 中的 `edit`、`publish`、`manage` 降为 `run`。
- [x] E0.2 权限：`enterprise_agents:manage`、`enterprise_kbs:manage`；`can_maintain_agent`、`can_use_agent`、`can_manage_kb`、`can_maintain_kb_content`（`design.md` 2.2）；`AGENT_PERMISSIONS` 收窄为 `view`、`run`。
- [x] E0.3 接口：工作台的创建接口写入 `personal`，管理后台的创建接口写入 `enterprise`；知识库管理员的增删查；个人资源治理（查看、停用、删除、转为企业资源，视需要确认的项 1）；列表与详情返回 `ownership`、`can_maintain`。
- [x] E0.4 绑定检查：企业智能体不能绑定个人知识库；绑定范围覆盖检查。
- [x] E0.5 测试：两种归属的维护权矩阵；共享只授予使用；知识库管理员只能维护内容；绑定方向；审计 detail。
- [x] E0.6 文档：`docs/architecture.md` 2.10、2.11 与相关模块文档。
- 实施说明（2026-11-12）：迁移 `e5f6a7b8c9d0_resource_ownership`（现有智能体与知识库设为 `enterprise`，角色授权 `manage` → `view` + `run`，`edit`、`publish` → `view`）。判断函数在 `agents/access.py`（`can_maintain_agent`、`can_use_agent`）与 `knowledge/access.py`（`can_manage`、`can_maintain`、`can_govern` 及对应的 `manageable_base`、`maintainable_base`、`governable_base`）。管理入口 `apps/api/.../http/admin_resources.py`（`/tenants/{id}/admin/agents`、`/admin/knowledge/bases`、知识库管理员、转为企业资源）。共享到共享空间改为需要维护权，列出与撤销另对 owner、admin 开放。草稿对维护者可见（此前只对 owner、admin）。owner、admin 对他人的个人智能体持有 `view` + `manage`（归档），不能编辑、发布、运行，也不能把它分配给别人。测试 `tests/test_resource_ownership.py`（8 项）；全量 pytest 通过（分三批运行，共约 1700 项）。前端入口按计划在 E2 实现。

## E1 租户与个人区

- [x] E1.1 迁移：删除 `personal` 租户及数据并收紧 `kind` 约束；`knowledge_bases.visibility`；`enterprise_policies`；`tenant_roles.builtin`。
- [x] E1.2 注册只创建企业；删除个人空间相关的后端分支与测试；登录默认进入上次使用的企业。
- [x] E1.3 知识库可见范围：`can_read` 按可见范围判断；修改可见范围的冲突检查。
- [x] E1.4 企业策略：接口与三处检查。
- [x] E1.5 企业级管理角色与审计正文权限。
- [x] E1.6 删除跨企业的 `/admin/*` 接口及服务函数与测试。
- [x] E1.7 测试：注册即创建企业、可见性矩阵、三项策略、内置角色不可删除。
- [x] E1.8 PostgreSQL 门禁：完成路线图 2.9，并覆盖本提案新增的列与表。
- [ ] E1.9 文档：`docs/architecture.md`、`docs/roadmap.md`（新增企业化步骤，2.9 改为前置门禁，9.1 由 E4 承接）、`configs/README.md`、`README.md`。
- 实施说明（2026-11-12）：迁移 `f6a7b8c9d0e1_enterprise_tenancy`。**偏离**：提案写的是“删除个人空间及数据”，迁移改为把残留的个人空间**原地改为企业**（不删数据），因为迁移也会在非开发库上执行；开发库 `nexus.db` 中本来没有个人空间，结果相同（已用其副本验证升级）。注册接口仍接受 `space_kind` 以兼容现有前端，但一律创建企业。自建智能体不再要求 `agents:write`，改由企业策略 `self_build_agents` 决定（viewer 不能自建）。知识库：新建个人库默认 `private`、企业库默认 `tenant`，迁移把已有库设为 `tenant`。`audit:read_content` 已加入权限目录，但目前审计接口只返回元数据，没有可查看的正文，等有正文查看功能时再接入。E1.3 中“不属于任何企业时进入创建或加入企业页”的前端部分随 E2 实现（登录接口此时返回空的 `active_tenant`）。测试 `tests/test_enterprise_policy.py`（7 项）并改写了依赖个人空间、个人模型默认开启、跨企业共享默认开启的旧测试；全量 pytest 三批通过。
- E1.9 未完成：本机没有 PostgreSQL（`NEXUS_TEST_POSTGRES_URL` 未设置），需要目标环境。

## E2 前端重构

- [x] E2.1 建立 pnpm workspace：根 `package.json`、`pnpm-workspace.yaml`（含 catalog）、`tsconfig.base.json`；`core`、`workspace`、`admin` 骨架；边界检查测试。
- [ ] E2.2 删除清单（`design.md` 4.5），含连带的依赖、文案与测试。
  - [x] E2.2.1 删除 `views/system/`、平台管理路由与守卫、设置和头像菜单中的平台管理入口；清理专属模型目录适配器、测试及无复用的入口文案。
  - [x] E2.2.2 删除 Wails 绑定、桌面自动登录与 Lite 地址恢复、桌面更新设置；已有令牌恢复与部署允许的开发登录保留。
  - [x] E2.2.3 注册页移除个人空间选择，自助注册只创建企业；邀请注册仍加入既有企业，不要求填写新企业信息。
  - [x] E2.2.4 删除助手及其独占的调用入口、状态、文案与测试，保留普通对话所需的工具卡片与编辑流程。
  - [ ] E2.2.5 删除 Ollama/Cloud 设置、CLI/Chrome/Claw/API 集成与本地浏览器连接入口；迁移 IM/embed 到智能体渠道、MCP endpoint 到个人设置后取消集成页。
- [ ] E2.3 抽取 `core`：请求层与接口、store、composables、directives、utils、types、i18n、样式与主题、共用组件（登录与扫码登录、改密、企业切换、布局骨架、空状态、错误页、文档预览、Markdown、智能体编辑器、知识库编辑器、IM 渠道面板）。
- [ ] E2.4 员工工作台：对话、我的智能体、我的知识库、我维护的企业知识库、企业分配、技能、记忆、产物、自动化、共享空间、个人设置；单智能体模式；`embed.html` 第二入口；手机宽度布局。
- [ ] E2.5 企业管理后台：企业信息、成员、部门架构、角色与权限、企业策略、企业智能体、企业知识库（含知识库管理员）、个人资源治理、模型、工具与技能、MCP、存储与检索、共享空间、运行状况、审计。
- [ ] E2.6 后端配合（`entries` 已完成，接口前缀迁移未做）：`/auth/me` 的 `entries`；管理接口前缀 `/api/v1/tenants/{id}/admin/...`（旧路径保留一个版本周期）。
- [x] E2.7 外部向量库与存储后端连接接入网络出口策略，并补私有地址被拒的测试。
  - 实施说明（2026-11-12）：`knowledge/connections.py` 在保存与测试向量库、原文件存储、图存储时检查地址：`url`、`dsn`、`endpoint` 的主机必须全部解析为公网地址，否则须列入 `[model_network].private_host_allowlist`。**追加**：发现企业管理员可以新建以任意服务器路径为存储的 `sqlite` 向量库与 `local` 原文件存储，SaaS 下等于读写宿主机文件，现默认拒绝，`[knowledge].allow_tenant_local_stores = true` 时放行（只适合单企业部署）。局限：只在保存与测试时检查，不对之后的每次连接固定地址（DNS 之后变化不会被发现）。`/auth/me` 与登录响应的每个成员身份增加 `entries`（`workspace`，有治理权限时加 `admin`）。测试 `tests/test_store_connections.py`。
- [ ] E2.8 构建与测试：`pnpm build` 产出两份产物且工作台不含管理后台代码；`pnpm type-check`、`pnpm test`、两个应用的浏览器测试；记录本机构建的内存情况。
- [ ] E2.9 文档：`AGENTS.md` 前端命令（并更正其中“Element Plus”的旧描述）；`apps/web` 父模块文档与三个项目的 `README.md`；`docs/architecture.md` 1.4 与 2.15；反向代理示例。
- 实施进度（2026-11-12，继续 E2）：已建立三个项目、catalog、唯一锁文件、严格类型配置、独立 Vite 入口和依赖方向检查。原应用迁入 `workspace`；API 及认证、缓存、主题基础逻辑的传递依赖、语言包、登录与改密组件抽到 `core`。管理入口读取当前企业成员身份的 `entries`；管理应用当前只有登录、强制改密及明确标注未接入的首页骨架。E2.3、E2.9 部分完成，均未整体勾选。E2.2 清单已部分删除，尚未迁移管理业务页或完成工作台导航重构，不能宣称工作台产物已隔离管理代码。
- 平台/桌面/注册批验证（2026-11-12）：锁文件安装、工程边界/PDF 复制 4 项、公共包 166 项、管理应用 1 项测试通过；工作台全量 1991 项中 1986 项通过、5 项跳过、0 失败，已完成前批迁移修复后的全量复测。公共包与管理应用类型检查通过（Node 堆限制 768MB）；282 个 Vue SFC 脚本编译与 2383 个本地导入解析通过。
- E2.2.1–E2.2.3 实施说明：平台管理专属页面、模型目录适配器、桌面绑定和自动登录已删除；共享审计的历史动作翻译保留。注册表单只创建企业，邀请注册只提交邀请与账号字段。工作台改密路由要求认证，临时密码账号先改密；管理应用的邀请和开户路径携带原查询参数转交员工应用，未知路径使用公共 404。
- E2.2.4 实施说明：删除助手组件、设置、会话/布局状态、上下文发布与独占文案；普通聊天的工具卡片、资源变更刷新继续使用原契约。模型/MCP 的一次性表单草稿移入 `workspace/src/stores/pageDrafts.ts`，切换企业、账号或退出时同步清空，同身份刷新保留；智能体和自动化写入授权级别保留。助手关联回归 72 项、公共包 166 项、工程边界/PDF 复制 4 项通过；公共包类型检查、草稿与工具链接的定向类型检查通过；272 个 SFC 脚本和 2334 个本地导入检查通过。本批未再次执行工作台全量，前批全量结果见上一条。
- 验证条件：本机约 1.9GB RAM、4GB Swap。构建被系统以 137 终止，降低堆限制后完整工作台类型检查触及 Node 堆上限；完整双应用构建、工作台类型检查与浏览器验收仍未通过。继续保留 E2.8 未完成状态。边界、SFC 编译、公共包与迁移回归结果见本次提交说明，不能替代完整验收。


- E2.2.5 实施进度：已删除 Ollama/Cloud 配置页、API/CLI/Chrome/Claw 集成及本地浏览器连接入口；IM 迁入智能体渠道页，面板抽入 `core`，改用 Nexus 接口，微信二维码本地编码、按所有者绑定并清理过期轮询。MCP endpoint 迁入账户设置，按 `tools:manage` 管理，知识库名称选择与只读工具白名单对应真实后端，一次性令牌和旧确认弹窗在作用域变化时失效。旧 IM/embed/MCP 书签兼容迁移，旧集成页已删除。
  - 验证（2026-11-13）：工作台全量 1954 项中 1949 项通过、5 项跳过、0 失败；公共包 173 项、管理应用 1 项、工程边界/PDF 复制 4 项通过。公共包与管理端类型检查、新渠道/MCP 页定向类型检查通过；261 个 SFC 脚本与 2232 个本地导入检查通过。工具结果动态风险翻译有保留测试；策略阻止创建、二维码停止轮询、在途响应隔离、令牌与旧确认弹窗失效均有组件覆盖。完整工作台构建/类型检查和浏览器验收仍未完成，沿用 E2.8 的内存与测试接入限制。根测试脚本受本机全局 pnpm 版本冲突影响，本批使用 Corepack 固定版本分别执行三个项目测试。
  - 尚未完成：embed 后端没有可用渠道契约，页面仅标注计划；当前 endpoint 仍为企业作用域，个人令牌持有/签发权限需在 E2.4/E6 补齐。因此 E2.2.5、E2.2、E2.3 和 E4.7 不整体勾选，管理后台渠道审核也仍待实现。

## E3 企业微信：企业、多应用与登录

- [x] E3.0 核对企微官方文档（`design.md` 6.4 与 7.2 所列各项），结果记入设计。（7.2 的智能机器人部分随 E4.0 核对）
- [ ] E3.1 `tenant_wecom_corps`、`tenant_wecom_apps`；删除 `configs [wecom]`；管理后台的企业绑定与应用列表页（主页地址复制、扫码登录标记）。（后端与接口已完成；`[wecom]` 暂未删除；页面随 E2）
- [x] E3.2 企微内免登：`/wecom/apps/{app_id}/entry` 与回调；按用途跳转；自动开户。
- [ ] E3.3 扫码登录：按企业编码找到扫码应用；登录页入口。（接口已完成，登录页入口随 E2）
- [x] E3.4 通讯录回调验签解密；全量同步与增量；离职撤销成员身份。
- [x] E3.5 测试：三种用途的跳转与权限拒绝、一个智能体至多一个应用、扫码登录、自动开户、离职后请求被拒；用假的 WeCom 客户端。
- 实施说明（2026-11-12）：迁移 `a7b8c9d0e1f2_wecom_apps`；平台 `nexus_platform/wecom/`（`client.py` 协议与地址、`crypto.py` 回调签名与 AES、`service.py` 配置、登录、同步、回调），HTTP 实现 `nexus_connectors/wecom/client.py`（connectors 新增 httpx 依赖，`uv.lock` 已更新），接口 `apps/api/.../http/wecom_apps.py`，worker `wecom_sync.py`（每天同步，或在请求同步、通讯录回调后尽快同步）。测试 `tests/test_wecom_apps.py`（7 项）。
  - **偏离一**：没有单独的“通讯录同步密钥”。官方文档说明 2022-08-15 起通讯录同步助手配置的新 IP 不能再调用读取接口，而自建应用自己的密钥可以读取其可见范围内的部门与成员，所以同步使用扫码登录应用（没有时用第一个工作台应用）的密钥；读不到的部门与成员不会进入 Nexus。成员与部门名称在管理员未授权时可能缺失，缺失时用 id 代替。
  - **偏离二**：`configs [wecom]` 与旧的部署级扫码登录、绑定接口（`/api/v1/auth/wecom/start|callback|bind/start`）暂时保留，前端切换到新入口（E2）后再删除。
  - 离职：通讯录回调的 `delete_user` 立即撤销成员身份；同步时不在可见范围内的成员也撤销；owner 永不被撤销。审计的操作者记为企业创建者，并在 metadata 写 `by = wecom`（审计表的操作者不能为空）。
  - 局限：同步失败后每分钟重试一次（尚无退避）；应用消息（非事件）的处理留给 E4 的渠道。

## E4 IM 渠道

- [x] E4.0 比较参考实现并核对各平台条件，结论记入设计。（结论见下方实施说明）
- [x] E4.1 `agent_channels`、`channel_session_bindings`（另有 `channel_messages` 去重、`channel_deliveries` 待发回复）；企业策略的 `personal_wecom_channels`、`personal_external_channels` 生效。
- [x] E4.2 worker 渠道连接管理器：租约领取、长轮询、续租、每 worker 连接上限（50）。
- [ ] E4.3 企微智能机器人渠道（企业与个人智能体）；`agent` 用途自建应用的消息渠道。（自建应用消息已完成；智能机器人未做，标记为 `unverified`）
- [x] E4.4 个人企微机器人审核：待审核、通过、驳回、停用，审计；策略收紧时停用已启用渠道。（工作台消息通知未做，审核结果在渠道列表中显示）
- [x] E4.5 微信渠道：iLink 扫码绑定、长轮询收消息、只服务绑定者、令牌失效转 `expired`。
- [ ] E4.6 QQ 渠道：扫码创建绑定或手动填写凭据、绑定码认领、只服务绑定者。（未做，标记为 `unverified`；认领规则已在入站处理中实现）
- [ ] E4.7 前端：智能体“渠道”页、管理后台“渠道审核与总览”。（接口已完成，页面随 E2）
- [x] E4.8 测试：群聊/会话隔离、无使用权的回复、非成员被拒、重复消息只处理一次、未审核与被策略停用的渠道、非绑定者的微信消息不处理、同一渠道只有一个租约持有者。
- 实施说明（2026-11-12）：迁移 `b8c9d0e1f2a3_agent_channels`；平台 `nexus_platform/channels/service.py`（创建规则、审核、策略收紧、入站处理、回复、租约）；`nexus_connectors/wechat/ilink.py`（按 octop-gateway `channels/weixin` 移植，只处理文字）；接口 `apps/api/.../http/channels.py`，企微回调里的应用消息转给渠道；worker `channels.py`（回复发送在空闲任务里、微信长轮询在 Run 事件循环里）。回复在 Run 停下时发送（完成、失败、取消，或需要人工确认/输入时提示到工作台处理），超过 1800 字截断并附工作台链接；只有网络类错误重试，最多 3 次。测试 `tests/test_channels.py`（5 项）。
  - **未完成**：企微智能机器人（长连接协议见 WeKnora `internal/im/wecom/longconn.go`，需要真实机器人验证）与 QQ 官方机器人（octop-gateway `channels/qq` 约 2600 行，个人开放范围与扫码创建流程未核对）两种渠道只保留数据与规则，创建时返回 `channel_kind_unverified`。
  - **未核对**：腾讯 iLink 接口的使用条款与令牌有效期；实现依据参考项目，没有在真实微信上验证。
  - 局限：群聊里按（渠道、会话、成员）隔离会话，但企微自建应用消息只有单聊；渠道连接没有按企业限流。

## E5 组织驱动授权

- [x] E5.1 部门、成员授权（`agent_audiences`，只授予使用权）与知识库按部门、成员开放（`knowledge_base_audiences`，`visibility = 'scoped'`）；部门可含下级部门。
- [ ] E5.2 前端：分配与共享对话框增加部门与成员。（接口已完成，页面随 E2）
- 实施说明（2026-11-12）：迁移 `c9d0e1f2a3b4_audiences`；`authz/audiences.py` 按检查时的组织关系展开（成员所在部门及其全部上级，逐级向上查找，没有用递归 CTE）；接口 `apps/api/.../http/audiences.py`（`PUT` 整体替换）。智能体由维护者分配（个人智能体只有创建者），知识库由管理者设置。绑定规则：`scoped` 库只有在智能体的使用者正好是其部门与成员受众、且被库的受众覆盖时才能绑定；有角色授权或共享空间共享的智能体只能绑定 `tenant` 库；收窄库的受众或可见范围时，若会让已绑定它的智能体的使用者读不到，拒绝（`kb_in_use`）。覆盖判断是保守的：部门受众必须由同一部门或带下级的上级部门覆盖。测试 `tests/test_audiences.py`（4 项）。
  - 按决定 5 的需要确认项，知识库管理员仍只能按成员指定，未扩展到部门与角色。

## E6 成本与配额

- [x] E6.1 `usage_ledger` 累加与用量报表（成员、智能体、模型、日期、部门）。
- [x] E6.2 三级月度上限的准入检查。
- 实施说明（2026-11-12）：迁移 `d0e1f2a3b4c5_usage`；`nexus_platform/usage/service.py`；接口 `apps/api/.../http/usage.py`。Run 结束时 worker 把该 Run 的 `model.completed` 事件中归一后的用量加入当天的（企业、成员、智能体、模型）行，每个 Run 只加一次；空闲任务补记漏掉的 Run（也会逐步补记迁移前已结束的 Run）。上限按“输入 + 输出”计算，缓存计数只报告不计入；部门上限统计检查时位于该部门及其下级的成员。超出时提交 Run 返回 429 `quota_exhausted`，进行中的 Run 不受影响。按部门的报表按成员的主部门归类。测试 `tests/test_usage.py`（4 项）。
  - 局限：没有费用（金额）统计，只有 Token；上限只在提交时检查，一个 Run 内的用量可以超过剩余额度。

## E7 数据治理

- [x] E7.1 按 `retention_days` 留存清理。
- [x] E7.2 审计导出与哈希链。
- 实施说明（2026-11-12）：`nexus_platform/governance/retention.py`、接口 `apps/api/.../http/governance.py`（`GET /tenants/{id}/admin/audit/export`，需 `audit:read`）、worker 每小时最多一次的保留清理。测试 `tests/test_governance.py`（3 项）。
  - **偏离一**：保留期到了以后，删除会话的**内容**（消息、该会话 Run 的事件、产物文件与记录），会话行保留为状态 `purged` 的空壳，而不是删除整行；因为 Run、用量、审计、渠道绑定、记忆快照等多张表引用会话与 Run，整行删除风险高。有排队、运行中或等待中的 Run 的会话不清理。
  - **偏离二**：哈希链在导出时计算并写在导出文件的每一行（`prev_hash`、`hash`），用于发现导出文件被改动、删行或调换顺序；没有在审计表中存储哈希字段，因此不防数据库内部的修改。存储式哈希链需要按企业串行写审计，留待评估。
  - 局限：会话列表仍会显示 `purged` 的空会话；法务保全（暂停清理）未做。

## 收尾

- [ ] 同步 OpenSpec 规格、路线图与模块文档后归档。
