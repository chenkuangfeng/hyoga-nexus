# 平台设计

`models/provider_settings.py` 提供模型设置应用服务；持久化按领域组织于 `persistence/models/`，通过原 `nexus_platform.persistence.models` 路径导出。`model_providers` 表保存空间与可选用户归属，`provider_models` 关联既有不可变模型版本，`model_defaults` 按空间和用户/空间范围保存默认。

`provider_credentials` 保存与凭据引用和供应商绑定的认证密文；密文内绑定凭据 ID，防止跨引用替换。部署端配置 `NEXUS_CREDENTIAL_ENCRYPTION_KEY`，不存入数据库。worker 使用 StoredCredentialResolver，环境凭据继续走原解析器。

修改 API 地址必须提供新 Key，产生新的凭据引用与模型版本；旧版本保留原地址和原凭据。同一地址替换 Key 属于轮换，已有版本下一次解析使用新值；已经取得凭据并发出的请求不会被撤回。停用在下一次授权/模型回合生效，不声称能终止供应商已经接收的请求。

权限在设置查询/修改、Agent 创建与发布、Session/Run 创建、worker 准备与每次模型回合检查。模型设置之外的旧模型编辑接口拒绝操作受管理模型或引用其加密凭据，避免旁路。

数据库迁移 `c8d240ab1701` 创建四张附加表，保留既有数据。PostgreSQL 并发专项最后执行；SQLite 回归不能替代目标环境验收。加密和网络决策见 [总体架构 2.13 节](../../../docs/architecture.md)。

## Native 状态与治理

`runs/settings.py` 持久化个人 Native 默认值及乐观版本；只有之后创建的 AgentVersion 使用这些默认值。`runs/directives.py` 按 Run 所有者和幂等键保存追加指令。`runs/approvals.py` 将动作审批绑定 Run 配置哈希和原工具调用，审批后重新入队，执行点重新授权、一次性消费，已完成工具不重放。该逐调用审批尚未覆盖参考项目的长期/自动化 AgentGrant 全部语义。

`memory/service.py` 是平台门面，`memory/repository.py` 实现 `nexus_memory` 的存储端口；个人记忆/SOP 的草稿审核、发布、指针索引、授权读取、归档和追加版本恢复规则位于 `packages/memory`。模型只能提出草稿；发布由用户界面发起。`sessions/fork.py` 在校验授权及空闲状态后创建模型分支，复制历史并记录来源，原会话保持原版本。

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

## 租户角色

`tenants/roles.py` 管理租户自定义角色。角色是菜单键（`authz/catalog.py` 中的 `MENUS`）与后台 API 权限键（`API_PERMISSIONS`）的集合，只能引用目录内的键，否则返回 422。表：`tenant_roles`、`tenant_role_menu_grants`、`tenant_role_api_grants`、`tenant_user_roles`（迁移 `a6c2d8e4f1b7`）。`tenant_user_roles` 用复合外键保证成员与角色属于同一租户。

有效权限为成员的全部角色授权并集；owner 与 admin 隐式拥有完整目录。非活跃成员没有任何权限。管理角色需要 `roles:manage`，且只能授予操作者自己拥有的菜单与 API 权限，防止越权。API 位于 `/api/v1/tenants/{id}/roles`、`/members/{id}/roles/{role}`、`/me/permissions`、`/role-assignments` 与 `/agent-grants`（后两者供管理界面回显）。

成员管理、模型配置与凭据、工具启用、审计查询分别要求 `members:manage`、`models:manage`、`tools:manage`、`audit:read`（owner/admin 隐式拥有）。创建智能体需要 `agents:write`。

## 智能体授权

`agents/access.py` 与 `tenant_agent_grants`（迁移 `b7d1e5c3a9f2`）按角色授予智能体级权限：`view`、`run`、`edit`、`publish`、`manage`。`manage` 蕴含全部，`publish` 蕴含 `edit` 与 `view`，`edit` 蕴含 `view`，规则见 `authz/catalog.py`。owner、admin 与智能体创建者保留原有完整权限。无 `view` 的成员看不到智能体（返回 404），其他缺失权限返回 403。智能体列表只返回可见智能体。创建会话需要 `run`；修改草稿需要 `edit`；发布需要 `publish`。角色管理者只能授予自己持有的智能体权限。

智能体绑定的工具、技能与知识库沿用已有的资源绑定（`ResourceBindingRecord`），使用时按智能体配置执行，不逐用户重新检查。Run 提交阶段目前只复核会话所属用户的成员身份，尚未在每次 Run 提交时复核 `run` 权限，这是后续需要补齐的缺口。

模型设置中的 `can_manage_tenant` 等 UI 标记、资源授权（`authz/resources.py`）仍按 owner/admin 判断，尚未迁移到目录权限。
