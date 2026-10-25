# 平台设计

`models/provider_settings.py` 提供模型设置应用服务；持久化按领域组织于 `persistence/models/`，通过原 `nexus_platform.persistence.models` 路径导出。`model_providers` 表保存空间与可选用户归属，`provider_models` 关联既有不可变模型版本，`model_defaults` 按空间和用户/空间范围保存默认。

`provider_credentials` 保存与凭据引用和供应商绑定的认证密文；密文内绑定凭据 ID，防止跨引用替换。部署端配置 `NEXUS_CREDENTIAL_ENCRYPTION_KEY`，不存入数据库。worker 使用 StoredCredentialResolver，环境凭据继续走原解析器。

修改 API 地址必须提供新 Key，产生新的凭据引用与模型版本；旧版本保留原地址和原凭据。同一地址替换 Key 属于轮换，已有版本下一次解析使用新值；已经取得凭据并发出的请求不会被撤回。停用在下一次授权/模型回合生效，不声称能终止供应商已经接收的请求。

权限在设置查询/修改、Agent 创建与发布、Session/Run 创建、worker 准备与每次模型回合检查。模型设置之外的旧模型编辑接口拒绝操作受管理模型或引用其加密凭据，避免旁路。

数据库迁移 `c8d240ab1701` 创建四张附加表，保留既有数据。PostgreSQL 并发专项最后执行；SQLite 回归不能替代目标环境验收。加密和网络决策见 [ADR-0004](../../../docs/adr/0004-model-provider-settings.md)。

## Native 状态与治理

`runs/settings.py` 持久化个人 Native 默认值及乐观版本；只有之后创建的 AgentVersion 使用这些默认值。`runs/directives.py` 按 Run 所有者和幂等键保存追加指令。`runs/approvals.py` 将动作审批绑定 Run 配置哈希和原工具调用，审批后重新入队，执行点重新授权、一次性消费，已完成工具不重放。该逐调用审批尚未覆盖参考项目的长期/自动化 AgentGrant 全部语义。

`memory/service.py` 与 `repository.py` 提供个人记忆/SOP 的草稿审核、发布、指针索引、授权读取、归档和追加版本恢复。模型只能提出草稿；发布由用户界面发起。`sessions/fork.py` 在校验授权及空闲状态后创建模型分支，复制历史并记录来源，原会话保持原版本。

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

`runs/ports.py` 定义无 ORM 的查询与事务协议；`runs/repository.py` 实现 Run 可见性、事件顺序和 Outbox 领取；`identity/repository.py` 在同一事务内解析用户与当前成员权限。事件写仓储只 flush，不自行 commit；调用者持有父 Run 锁（新建 Run 时依靠事务内尚不可见的新行），保持 sequence 唯一。共享实体唯一 Base 位于 `persistence/base.py`，模型包仅重新导出，Alembic 继续装配同一 metadata。

当前提交、取消、准备和存储适配仍直接使用 SQLAlchemy；尚未实现所有领域服务与 ORM 的隔离。此处没有迁移 WeKnora 的所有 Session 功能或 GenericAgent 循环。源码迁移范围与未完成项保留在已确认的 OpenSpec 变更中。
