# 平台设计

`models/provider_settings.py` 提供模型设置应用服务；持久化按领域组织于 `persistence/models/`，通过原 `nexus_platform.persistence.models` 路径导出。`model_providers` 表保存空间与可选用户归属，`provider_models` 关联既有不可变模型版本，`model_defaults` 按空间和用户/空间范围保存默认。

`provider_credentials` 保存与凭据引用和供应商绑定的认证密文；密文内绑定凭据 ID，防止跨引用替换。部署端在 `configs/nexus.toml` 的 `[security].credential_encryption_key` 配置主密钥，不存入数据库。worker 使用 StoredCredentialResolver，部署凭据（`[model_credentials]`）继续走原解析器。

修改 API 地址必须提供新 Key，产生新的凭据引用与模型版本；旧版本保留原地址和原凭据。同一地址替换 Key 属于轮换，已有版本下一次解析使用新值；已经取得凭据并发出的请求不会被撤回。停用在下一次授权/模型回合生效，不声称能终止供应商已经接收的请求。

系统租户与内置资源（提案 2026-11-07-skill-evolution）：`nexus_platform/system.py` 在 API 与 worker 启动时幂等创建保留的系统租户（`kind = 'system'`，固定 id，保留用户不可登录）并把 `BUILTIN_TOOL_NAMES` 登记其名下；内置技能由平台管理员导入同一租户。`authorize_resource` 对 `skill` 与 `tool` 且源租户为系统租户的资源放行（校验登记行存在、生效、本空间未停用），不要求授权行；调用未指明来源、本空间也没有自己的登记时同样回落到系统租户。智能体草稿绑定在本空间没有自己的登记时把来源归一为系统租户（外键要求绑定指向已登记资源），本空间自己的登记优先并保持来源。`tenant_builtin_disabled` 记录空间对内置资源的停用，目录、发布校验与调用授权三处读取；已发布的智能体版本的绑定保留，但调用被授权拒绝。系统租户不出现在租户列表、成员、平台汇总与空间选择中（没有成员即不可选，平台管理员列表与计数显式排除）。

权限在设置查询/修改、Agent 创建与发布、Session/Run 创建、worker 准备与每次模型回合检查。模型设置之外的旧模型编辑接口拒绝操作受管理模型或引用其加密凭据，避免旁路。

新接入的企业服务商及首个模型在同一 `models:manage` 授权事务内保存。失败时一并回滚服务商、加密凭据、模型档案及审计。

追加模型版本时沿用上一版本的模型选项。显式提交空字符串思考强度会清除新版本的该选项，使用服务商默认设置。

企业模型编辑接入与追加版本在同一事务执行。地址变化要求替换 Key。新接入只关联当前模型，旧接入及凭据继续供引用历史版本的执行解析。企业模型目录的删除操作先检查智能体、知识库与记忆设置的当前引用，只返回分类计数。

企业模型复制从当前版本读取模型类型、上游模型 ID 和选项，在同一服务商锁内创建新档案及第一个版本，并记录 `provider.model_copied`。副本共享服务商凭据引用，默认值和已发布智能体维持原有绑定。展示名保存在版本选项中，历史档案用上游模型 ID 作为展示名。

数据库迁移 `c8d240ab1701` 创建四张附加表，保留既有数据。PostgreSQL 并发专项最后执行；SQLite 回归不能替代目标环境验收。加密和网络决策见 [总体架构 2.13 节](../../../docs/architecture.md)。

## Native 状态与治理

`runs/settings.py` 持久化个人 Native 默认值及乐观版本；只有之后创建的 AgentVersion 使用这些默认值。`runs/directives.py` 按 Run 所有者和幂等键保存追加指令。`runs/approvals.py` 将动作审批绑定 Run 配置哈希和原工具调用，审批后重新入队，执行点重新授权、一次性消费，已完成工具不重放。审批记录 `reason`（`policy` / `guard`）与 `risk`；以 `remember=session` 批准的策略审批写入 `action_grants`（ActionGrant，按会话、智能体版本、工具名），之后同会话的调用经 `grant_for_call` 跳过审批，`destructive` 工具与守卫触发的审批不能放行；放行列表与撤销接口只对会话所有者开放（提案 2026-11-06-tool-call-hardening E）。自动化作用域的 ActionGrant 尚未使用。

`memory/service.py` 是平台门面，`memory/repository.py` 实现 `nexus_memory` 的存储端口；个人记忆/SOP 的草稿审核、发布、指针索引、授权读取、归档和追加版本恢复规则位于 `packages/memory`。模型只能提出草稿；发布由用户界面发起。`memory/switches.py` 读写长期记忆三级开关（空间 `memory_space_settings`、成员 `memory_capture_settings.memory_enabled`、智能体版本 `budgets.memory`），`memory_state` 供 Run 准备（索引与记忆工具）、工具授权（`memory_disabled`）和自动抓取（排队与规划）判断记忆是否可用。`memory/capture.py` 规划抓取任务时读取消息来源（`runtime_metadata.origin`、`tool_calls`）、按相关性挑选的已发布条目和最近被拒的主题，校验后的动作带主题、重要度、证据经 `propose` 成为草稿（openspec 2026-11-06-memory-evolution 第 1 阶段）。`memory/consolidation.py` 由 worker 空闲时调度整理：后台每人每天一次（需开启自动抓取），手动经 `POST /native/memory-consolidation` 排队（每分钟一次，只需保存了抓取模型）；模型确认后生成合并草稿，所有者审核前不发布、不归档。`memory/conversations.py` 为 `search_conversations`、`read_conversation` 工具提供历史会话检索：只读调用者本人在本空间的其他会话，只含用户与助手消息，按 `histories_allowed` 隐藏无权 Run 的消息，受记忆开关控制。`memory/vectors.py` 管理语义召回：空间选择 Embedding 模型，worker 空闲时为当前版本补向量，`search_memory` 时以检索者本人的 Key 嵌入查询并与关键词结果融合，失败退回关键词；Embedding 客户端由 worker 注入。Run 准备阶段按本轮问题注入相关记忆（`budgets.memory.recall` 可关闭），并发 `memory.used`（来源 `recall`）。`memory/interests.py` 统计抓取得到的主题在多少个会话中出现，达到空间阈值时生成 `interest` 草稿。`memory/providers.py` 管理外部记忆提供方：每个空间最多选一个已注册的提供方，在创建快照、准备 Run 和 Run 结束后调用，带截止时间与失败暂停，结果作为资料注入，写入只能成为草稿。`memory/retention.py` 每小时最多一次删除 30 天前被拒的草稿和 14 天前结束的抓取任务。`sessions/fork.py` 在校验授权及空闲状态后创建模型分支，复制历史并记录来源，原会话保持原版本。

迁移 `d9e351bc2802` 新增 Native 设置、动作审批、指令、摘要和记忆版本表，并为等待输入增加候选项。SQLite 已验证升级、重复升级和回退保留用户；PostgreSQL 专项仍待环境验收。


## Run 应用与事务边界

`runs/service.py`、`runs/execution.py` 保留旧函数和类的导入入口，业务逻辑分别位于：

| 模块 | 职责 |
| --- | --- |
| `submission.py` | RunSubmissionService：授权、固定配置、幂等冲突、消息/事件/Outbox 原子提交 |
| `queries.py`、`events.py` | RunQueryService/RunEventService：当前成员授权、所有者可见性与排他事件游标；重放不执行任务 |
| `leasing.py` | RunLeaseService：可用时间、过期租约、稳定排序、领取计数与旧 P1 无 Runtime 处理入口 |
| `cancellation.py`、`state.py` | 取消申请、队列终止与合法 Run 状态转换 |
| `preparation.py`、`context.py` | ExecutionPreparer：短事务内复核身份、授权、版本与租约，构造执行上下文 |
| `store.py` | DurableRuntimeStore：执行点租约、消息/事件、工具记录、记忆与检查点持久适配 |
| `inputs.py`、`messages.py`、`completion.py` | 输入回答幂等与重新入队、消息排序/历史授权、执行结束持久化 |

SqlAlchemyUnitOfWork 接受 API 借用会话或 worker 的 sessionmaker；前者不关闭会话，后者总是关闭。成功提交，异常回滚，不允许悄悄嵌套事务。所有绑定仓储共享这一事务中的会话。SQLite sqlite3 legacy 模式下，UnitOfWork 在首次保存点前确保真实 BEGIN；已由驱动或 Engine 建立事务时不重复 BEGIN。PostgreSQL 使用 SQLAlchemy 原生事务控制。

`runs/ports.py` 定义查询与事务协议，`command_ports.py` 定义写入端口。`repository.py` 实现 Run 可见性、所有者锁、幂等保存点和显式保存；`event_repository.py`、`queue_repository.py` 分别处理事件顺序和 Outbox 领取/投递；`identity/repository.py`、`submission_access.py` 在同一事务内复核用户、成员、模型和资源权限。事件写仓储只 flush，不自行 commit；调用者持有父 Run 锁（新建 Run 时依靠事务内尚不可见的新行），保持 sequence 唯一。共享实体唯一 Base 位于 `persistence/base.py`，模型包仅重新导出，Alembic 继续装配同一 metadata。

`domain.py` 的 Run、PendingInput 与 `configuration.py` 的配置值对象独立于 SQLAlchemy。仓储复制字段和 JSON，应用更改必须显式调用 save/consume 等写入端口才会持久化。`configuration_repository.py` 读取已锁定 Session 和固定发布版本；消息、输入和审计各有事务适配器。提交先复核当前权限再允许幂等重放；取消和输入只用 tenant+principal 的所有者锁，不沿用较宽的读取可见性。已消费相同回答先于 Run 当前等待状态判断，保留推进或取消后的合法重放；实际回答 key 不做 trim。

`compatibility.py` 将原函数调用装配到应用服务，返回本次仓储已跟踪的 RunRecord；不在提交后重新 SELECT，不开启另一事务。`service.py`、`execution.py` 和先前的职责模块入口继续保留。应用服务返回独立 Run 对象，直接导入提交、取消、输入和租约应用服务不会加载 SQLAlchemy。事件 writer 不自行提交；写入消息、输入、审计或队列的后续失败使此前 flush 的内容一起回滚。

执行点资源授权、ExecutionPreparer 和 DurableRuntimeStore 仍有直接 ORM 使用，尚未完成全部服务隔离。此处没有迁移 WeKnora 的所有 Session 功能或 GenericAgent 循环。源码迁移范围与未完成项以本模块文档为准。


RunLeaseService 的旧 P1 process 路径按原顺序锁 Delivery、校验 lease owner、锁 Run；已开始或曾尝试的执行标记 interrupted，取消优先于重试，首次执行在无 Runtime 时记录 started/failed。只有常规处理完成才清理租约字段；已终态的早退路径保留既有租约值并完成投递。该入口保留历史兼容，Native worker 仍由 ExecutionPreparer 和 DurableRuntimeStore 驱动。Delivery 是独立数据对象，后台按投递锁读取 Run 的内部端口不能用作用户可见性回退。

## 部署数据库配置

`configuration.py` 使用标准库 tomllib 集中解析 `configs/nexus.toml`，`resolve_database_url()` 按显式 URL、文件、环境变量顺序选取并验证连接串。`DatabaseConfigurationError` 继承 RuntimeError，错误不携带秘密。数据库工厂与 API/worker/Alembic 共用；读取规则和使用方式见 [configs](../../../configs/README.md)。不加载 dotenv，不在模块导入时读取配置。

## 租户与身份

平台的组织单位统一称为 Tenant（表 `tenants`，成员关系 `tenant_memberships`，API 路径 `/api/v1/tenants/...`）。迁移 `f3a7c1e2b9d4` 完成从 Workspace 的重命名：表、`*_workspace_id` 列及索引/唯一约束名均改为 tenant。SQLite 通过 `ALTER TABLE ... RENAME COLUMN` 与重建约束完成，并已通过升级、回退、再升级的回归测试；PostgreSQL 的约束和索引重命名 DO 块尚未在目标环境验证。

用户与外部身份分离：`users` 只保存平台内部用户与显示名；`user_identities(provider, scope, external_id)` 保存每个外部登录身份（Web/OIDC、企业微信、微信、QQ 等）。`scope` 为空串表示提供方没有租户级 ID，企业微信等需要按企业隔离时使用企业 ID。`identity/service.py` 的 `resolve_user` 按 (provider, scope, external_id) 解析或首次创建用户；`principal_for_user` 为已存在的内部用户选取一个可回解析的外部身份，供执行上下文复核授权。

成员状态位于 `tenant_memberships.status`（`active`、`suspended`、`revoked`），`suspended_at` 记录最近一次停用时间。`tenants/service.py` 的成员状态写入先锁企业、验证 `members:manage` 和 owner 边界，再记录 `tenant.member_status_changed`；至少保留一名 active owner。停用不删部门、资源或历史，身份与资源授权仍通过 `membership_is_active` 拒绝 suspended。邀请/申请接受与手工添加拒绝隐式恢复；企微登录保留人工停用，目录离职/移出范围仍撤销成员关系。

## 租户角色

`tenants/roles.py` 管理租户自定义角色。角色是菜单键（`authz/catalog.py` 中的 `MENUS`）与后台 API 权限键（`API_PERMISSIONS`）的集合，只能引用目录内的键，否则返回 422。表：`tenant_roles`、`tenant_role_menu_grants`、`tenant_role_api_grants`、`tenant_user_roles`（迁移 `a6c2d8e4f1b7`）。`tenant_user_roles` 用复合外键保证成员与角色属于同一租户。

有效权限为成员的全部角色授权并集；owner 与 admin 隐式拥有完整目录。非活跃成员没有任何权限。管理角色需要 `roles:manage`，且只能授予操作者自己拥有的菜单与 API 权限，防止越权。API 位于 `/api/v1/tenants/{id}/roles`、`/members/{id}/roles/{role}`、`/me/permissions`、`/role-assignments` 与 `/agent-grants`（后两者供管理界面回显）。

成员管理、模型配置与凭据、工具启用、审计查询分别要求 `members:manage`、`models:manage`、`tools:manage`、`audit:read`（owner/admin 隐式拥有）。创建个人智能体需要 `agents:write`，创建企业智能体与企业知识库分别需要 `enterprise_agents:manage`、`enterprise_kbs:manage`（owner、admin 默认持有）。

## 智能体授权

`agents/access.py` 按归属判断智能体权限（提案 2026-11-11-enterprise-saas 决定 2，迁移 `e5f6a7b8c9d0`）。`agents.ownership` 为 `personal` 或 `enterprise`：个人智能体只有创建者（仍是有效成员时）能编辑、发布、管理；企业智能体只有持有 `enterprise_agents:manage` 的成员能维护（owner、admin 默认持有，可授予自定义角色），与创建者无关。`tenant_agent_grants` 按角色只授予使用权 `view`、`run`（迁移把旧的 `manage` 改为 `view` + `run`，`edit`、`publish` 改为 `view`）。owner、admin 能看到全部智能体，并对他人的个人智能体保留治理权（查看、归档、转为企业智能体），但不能编辑、发布或运行。无 `view` 的成员看不到智能体（返回 404），其他缺失权限返回 403。草稿只对维护者与 owner、admin 可见，其余成员只看到已发布版本。创建会话需要 `run`；修改草稿需要 `edit`；发布需要 `publish`。工作台入口 `POST /tenants/{id}/agents` 创建个人智能体（需 `agents:write`），管理入口 `POST /tenants/{id}/admin/agents` 创建企业智能体（需 `enterprise_agents:manage`），归属不由请求参数决定。绑定检查：企业智能体不能绑定个人知识库，个人智能体只能绑定创建者本人的个人知识库与企业知识库；转为企业智能体前须先转换其绑定的个人知识库。角色管理者只能授予自己持有的使用权，因此 owner、admin 不能把他人的个人智能体分配给别人。共享到共享空间需要维护权，列出与撤销共享另对 owner、admin 开放。

智能体绑定的工具、技能与知识库沿用已有的资源绑定（`ResourceBindingRecord`），使用时按智能体配置执行，不逐用户重新检查。每次提交 Run 时复核调用者的成员身份与该智能体的 `run` 权限（`runs/submission_access.py`），撤权后下一次提交被拒绝。

智能体状态为 `draft`、`published`、`archived`。`agents/service.py` 的 `archive_agent` 把智能体归档（软删除，需要 `agents:write` 与 `manage`）：列表、共享智能体列表与详情不再返回它；新建会话与提交 Run 返回 409，已排队的 Run 在准备阶段以 `agent_archived` 失败；已发布版本、绑定与会话消息保留。`copy_agent` 把草稿复制为调用者创建的新草稿，绑定与模型逐项重新授权，不复制版本、共享与授权。

`agents/generation.py` 定义智能体级生成参数 `budgets.generation`（`temperature` 0–2，`reasoning_effort` 为 `off/auto/minimal/low/medium/high/xhigh/max`），创建与修改草稿时校验。运行准备阶段 `merged_model_options` 以智能体值覆盖模型档案的同名选项：`auto` 沿用模型档案，`off` 移除思考参数；故障转移模型同样适用，上下文压缩的摘要模型不适用。

模型设置中的 `can_manage_tenant` 等 UI 标记、资源授权（`authz/resources.py`）仍按 owner/admin 判断，尚未迁移到目录权限。

## 组织与人员

表：`org_units`（节点，`root_id` 指向所在树的根，`parent_id` 为空表示根）、`user_org_units`（人员与节点，`is_primary` 在每个用户上最多一个为真，由部分唯一索引保证）、`tenant_org_bindings`（空间与节点的多对多绑定，绑定覆盖节点子树）、`org_audit_records`（组织侧审计，`root_id` 不设外键，历史不随树消失）。迁移 `d1f5b8c2a9e4`；`users.is_platform_admin` 默认为假，由 `nexus_api.cli set-platform-admin` 设置。

服务位于 `orgs/service.py`。树的结构性修改在事务内锁定整棵树；移动节点时拒绝移入自身子树，并要求同一棵树内移动。主节点切换在同一事务中完成。删除节点要求没有子节点、人员和绑定。

空间视图按绑定节点的子树读取节点结构，并按用户去重列出人员。加入空间的接口只接受绑定子树内的人员，并需要 `members:manage`；owner 不能经此途径创建。组织管理接口只接受平台管理员，不使用租户角色，因此也不受空间的角色升级检查约束。

## Run 事件通道（runs/bus）

`config.py` 读取 `[run_events]` 与 `[deployment]`；`memory.py`、`redis_backend.py`、`database.py` 实现 `nexus_core.run_events` 的端口；`factory.py` 管理进程级通道；`hook.py` 在 `after_commit` 发布持久事件并在取消请求时发控制信号；`stream.py` 是订阅管线（数据库重放、通道消费、去重、补读、`resync`）。`control.py` 为 Redis 与数据库后端的控制唤醒与活动标记。配额在 `runs/quotas.py`，按模型限流在 `runs/model_limits.py`。

模型调用轨迹独立保存在 `run_trajectory_records`，不从 `RunEventRecord` 派生。`DurableRuntimeStore` 在每次模型尝试前记录模型可见的消息与工具定义快照，完成或失败后补写响应、供应商 usage、输入估算和 Run 累计 token；唯一键 `(run_id, sequence)` 在 Run 行锁下递增。`runs/trajectory.py` 先调用标准 `get_run` 授权，再按序返回记录，API 使用独立 `RunTrajectoryRecordView`。前端将其与授权会话消息组合成用户、助手和工具活动行；工具结果 API 仅暴露 opaque `tool_call_id` 用于关联，不返回整份运行元数据。该表用于受授权的诊断检查器，不改变事件重放和消息审计职责。

Redis 后端每个（事件循环，Run）一个共享的阻塞读取器，再扇出到该进程的订阅者；每个订阅者的队列有上限（2048 个事件），读得慢的订阅者被切断并收到 `BusUnavailable`，订阅管线随即改读数据库直到 Run 结束。memory 后端的订阅者在 Run 尚无事件时也会登记唤醒。压测与故障注入见 [run-events-benchmark.md](run-events-benchmark.md)。

## 知识库共享（shared_spaces/kb_shares）

`knowledge_base_shares` 记录库共享到共享空间的级别；`kb_shares.shared_levels` 按「共享级别、成员空间在共享空间的角色、本人在本空间的角色上限」取最小得到每个库的有效级别，`knowledge/access.py` 的 `can_read` 与 `readable_bases` 把它并入读取判定（与租户级 `resource_grants` 并列）。写入、设置与共享管理仍只属于所属空间，并按归属区分（见下一段）。有效级别规则与智能体共享共用 `agent_shares.effective_level`。

知识库按归属区分写权限（提案 2026-11-11-enterprise-saas 决定 2）。`knowledge_bases.ownership` 为 `personal` 或 `enterprise`。`knowledge/access.py` 提供三级判断：管理（设置、置顶、共享、维护人员）`can_manage`——个人库为创建者，企业库为 `enterprise_kbs:manage` 的持有者；内容维护（文档、分块、问答、标签、目录、Wiki、重建）`can_maintain`——管理者加上企业库在 `knowledge_base_maintainers` 中指定的知识库管理员；治理（删除、转为企业库）`can_govern`——管理者加上空间 owner、admin。对应的取库函数为 `manageable_base`、`maintainable_base`、`governable_base`。`base_view` 返回 `ownership`、`owned_by_me`、`can_manage`、`can_maintain`、`can_govern`，`can_edit` 等同 `can_maintain`，供沿用的 WeKnora 页面使用。`knowledge/ownership.py` 管理知识库管理员（只用于企业库，须是有效成员）与个人库转为企业库（只限 owner、admin）。管理入口位于 `apps/api/.../http/admin_resources.py`：`POST /tenants/{id}/admin/knowledge/bases` 创建企业库，`/admin/knowledge/bases/{kb}/maintainers` 增删查知识库管理员，`/admin/knowledge/bases/{kb}/convert-to-enterprise` 与 `/admin/agents/{agent}/convert-to-enterprise` 转换归属。

## 定时任务（schedule）

`schedule/rules.py` 校验三种规则（每 N 分钟、每天、每周一天，IANA 时区），`schedule/service.py` 是唯一的业务入口，`cronjob_*` 工具与 REST（`apps/api/.../http/schedules.py`）共用它：创建（工具按会话的智能体版本，REST 按智能体当前已发布版本）、更新（改规则或时区重算下次时间，改提示词重新扫描，挂起的任务仍需恢复）、暂停 / 恢复 / 删除、立即运行（不改 `next_run_at`，60 秒节流）、任务会话的运行列表、触发预览，以及到点触发 `fire_due`。他人的任务对普通成员一律是「不存在」；空间 owner / admin 可列出全部并读取、暂停，其余操作仍只限所有者。`ScheduleError` 由 API 的统一处理转成 `{error: {code, message}}`（404 / 403 / 409 / 429 / 422）。

## 沙箱产物（artifacts）

`artifacts/service.py` 在 Run 结束时登记沙箱 `/outputs` 下的文件：先在事务外流式复制并计算 `sha256`（`O_NOFOLLOW`，只收普通文件，复制中超限即放弃），再在一个事务里写 `artifacts` 行、`artifacts.registered` 事件与审计；上限与跳过原因见 `docs/architecture.md` 沙箱部分。读取与删除一律经会话授权：会话所有者或空间 owner / admin，其余按「不存在」处理。下载前再次确认副本位于产物根目录内、不是符号链接，副本缺失时报告不存在而不是出错。worker 侧入口是 `nexus_worker.artifacts.register_outputs`，在 Run 收尾调用且从不抛出，失败只记日志。


企业化（提案 2026-11-11-enterprise-saas E1，迁移 `f6a7b8c9d0e1`）：`auth/accounts.register` 一律创建企业（`space_kind` 只为兼容旧客户端而接受），企业编码缺省为随机生成；迁移把残留的个人空间原地改为企业并收紧 `tenants.kind`。`tenants/policies.py` 读写 `enterprise_policies` 并提供 `require_self_build`、`personal_models_allowed`、`require_external_sharing`，分别接在 `agents/service.create_agent`（个人智能体）、`models/provider_settings`（`provider_access` 与个人供应商创建）和两种共享入口上。`tenants/builtin_roles.py` 在 `create_tenant`、注册与默认企业引导时写入内置角色，`roles.update_role_grants` 拒绝修改内置角色。`knowledge/access.py` 的 `visible_in_space` 按 `visibility` 判断本企业成员的读取；`agents/service.py` 的 `check_binding_scope`、`agents_exposing_base` 保证他人可用的智能体只绑定 `tenant` 库。跨企业的 `/admin/tenants`、`/admin/summary`、`/admin/agents`、`/admin/sessions` 已删除。

企业化后续阶段（提案 2026-11-11-enterprise-saas E3–E7）：`wecom/`（`client.py` 协议、`crypto.py` 回调验签与 AES、`service.py` 应用配置、免登与扫码、通讯录同步、回调；HTTP 实现在 `nexus_connectors.wecom`）；`channels/service.py`（渠道创建规则、审核、策略收紧、入站转 Run、回复、租约；微信 iLink 客户端在 `nexus_connectors.wechat`）；`authz/audiences.py`（部门与成员受众）；`usage/service.py`（用量账本、报表与月度上限，提交 Run 时经 `SubmissionAccess.require_usage_quota` 检查）；`governance/retention.py`（保留期清理与审计导出）。worker 新增 `wecom_sync.py`、`channels.py`（回复发送、微信长轮询）以及用量记录与保留清理的空闲任务。


### 部门批量角色分配的授权边界

`tenants.membership.assign_role_to_unit` 在同一事务和企业锁内要求 `members:manage` 与 `roles:manage`，通过 `tenants.roles.require_grantable_role` 校验同企业角色及权限子集。单成员分配复用该校验助手，避免批量路径绕过既有授予范围约束。校验完成前不写入任何分配；启用部门的直接活跃非 owner 成员参与，已有分配跳过，不展开子树、不创建随组织变动继承的绑定，保留批量审计与 assigned/skipped 返回形状。

## 企微组织归属来源

`orgs.service.sync_managed` 把 source=wecom 或具有 external_id 的节点视为同步管理；更新/删除接口在企业锁内返回 Conflict，启用节点下仍可创建手工子部门。迁移 `a03b51d982ef` 为 user_org_units 增加 manual/wecom/mixed 来源，按现有 wecom_members.department_ids 精确回填企微来源，其余保守保留 manual。手工增加已有企微关联升为 mixed，删除 mixed 只去掉手工贡献；企微对账做相反的来源维护。主部门标记独立于来源，重复添加不会清掉原主部门。目录落库和手工组织写入复用企业锁与事务。现有数据无法追溯同一关联曾否被人工额外确认，回填以当前通讯录匹配结果为准。

## 知识库文档目录

`knowledge_folders` 保存显式目录，目录查询合并记录、文档路径和隐式父级。新建与重命名需要内容维护权。同名文件的版本和内容去重按目录计算。上传提交阶段重新校验权限和重复内容，原文件仍用 UUID 组成对象键。
