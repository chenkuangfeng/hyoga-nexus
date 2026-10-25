# 核心源码迁移与模块分布

## 实现方法

先逐批明确来源函数与依赖、输入/输出、状态/异常/重试、提示词、生命周期和原测试，再选择直接复制、等价翻译或明确适配；同名类、注释说 derived 和现有测试通过均不能当作迁移证据。GA Python 纯算法可复制，经鉴权/存储/异步边界包裹；WK Go 逻辑翻译为 Python 并逐项转换原测试断言。二者冲突采用下表中的显式方案，不静默拼接。

保持一个模型/工具执行循环。不能启动完整 GenericAgent.run 后在外面再套 NativeEngine；两项目贡献的行为由同一 RunOrchestrator/TurnExecutor 组合。现有 SDK adapter 内部只管理传输，不再次编排任务。

## 共享契约

将 core/runtime.py 的模型消息/请求/块、工具、预算/进度、事件和故障按 models.py、tools.py、budgets.py、events.py、errors.py 分入 core/runtime/ package；__init__ 继续导出原名。core/native.py 的行为策略与 hook DTO 同样按职责组织，旧导入保留。只移动实际稳定跨包契约，不把 ORM、平台 Repository 或 SDK 类型放入 core。

## 平台类与文件分布（目标，尚未实现）

| 路径 | 主类/职责 | 当前代码处理 |
| --- | --- | --- |
| platform/persistence/base.py | Base、共享 SQLAlchemy metadata | 从 models.py 提取唯一 Base，避免重复 metadata |
| platform/persistence/models/identity.py、workspace.py | UserRecord；WorkspaceRecord/MembershipRecord | 按领域拆分，保留表名/约束/旧导入 |
| platform/persistence/models/agent.py、resource.py | Agent/版本/绑定；资源/共享授权实体 | 分开配置版本与资源授权 |
| platform/persistence/models/model.py、credential.py | 供应商/模型/默认值；凭据引用与密文实体 | 秘密保留服务端，不混入执行状态 |
| platform/persistence/models/session.py、run.py、event.py | Session/Message；Run/进度；RunEvent | 会话内容、任务状态和事件各自组织 |
| platform/persistence/models/invocation.py、queue.py、audit.py | ToolInvocation；Outbox/lease；Audit | 副作用记录、任务投递和审计分开 |
| platform/persistence/models/memory.py、approval.py | 记忆版本/检查点；Prompt/ActionApproval/ActionGrant | 新授权实体用增量迁移，不用 ResourceGrant 冒充 |
| platform/<domain>/domain.py | 对应领域状态与不变量 | 业务对象不依赖 ORM 或厂商 SDK |
| platform/<domain>/ports.py、repository.py | Repository Protocol；SQLAlchemy adapter | core 只保留真正跨包契约，不堆入数据库 CRUD |
| platform/persistence/unit_of_work.py | SqlAlchemyUnitOfWork | 明确提交/回滚，现有授权与写入保持同一事务 |
| platform/runs/submission.py、leasing.py、events.py、cancellation.py | RunSubmissionService、RunLeaseService、RunEventService、RunCancellationService | 拆分 runs/service.py，旧函数经兼容 facade 调用 |
| platform/runs/preparation.py、store.py、inputs.py | ExecutionPreparer、DurableRuntimeStore、RunInputService | 拆分 execution.py 的配置准备、持久适配和回答恢复 |
| platform/approvals/service.py、grants.py | ApprovalService、ActionGrantService | 单次决定与可记忆授权独立；配置 hash/风险/撤权/期限明确 |

models/__init__.py 仅导出；迁移前保留原 `nexus_platform.persistence.models` 导入路径。将 models.py 改为同名 package 时，一次性更新依赖、Alembic metadata 装配与导出，不能同时注册两份实体。纯结构移动不得生成表重建；新增持久字段才写 Alembic 增量迁移。

## Native 与工具类分布（目标）

| 路径 | 主类/职责 | 来源主线 |
| --- | --- | --- |
| native/engine/facade.py | NativeEngine：保留现有构造/run API，组合服务 | 现有外部契约 |
| native/engine/orchestrator.py | RunOrchestrator：Run 起止与预算、回合调度 | GA loop；WK executeLoop |
| native/engine/turn.py | TurnExecutor：prepare/think/analyze/act/observe | WK runReActIteration；GA 单回合 |
| native/engine/state.py、completion.py、finalization.py | LoopState/IterationOutcome；ResponseClassifier；TurnFinalizer | 显式 continue/break/next、no_tool、done queue、终态事件 |
| native/engine/budgets.py、cancellation.py | RunBudgetTracker；取消信号与传输清理 | 不把计数、超时和停止散在同一 run 方法 |
| native/context/assembly.py、sanitizer.py | ContextAssembler、MessageSanitizer | 稳定历史与发送投影分离，修复孤立工具结果 |
| native/context/working.py、reminders.py | WorkingMemory、TurnReminderPolicy | GA key_info/history/summary/周期提醒 |
| native/context/token_estimator.py、calibration.py | TokenEstimator、UsageCalibration | WK usage+delta、工具 schema 与估算校准 |
| native/context/compaction/{cutpoint,compactor,checkpoint,overflow}.py | CutPointSelector、ContextCompactor、SummaryCheckpoint、OverflowRecovery | WK compaction/cutpoint/overflow/checkpoint |
| native/models/protocols/chat/{request,stream,response}.py | ChatRequestBuilder、ChatStreamDecoder、ChatResponseDecoder | WK Chat 协议和 GA 对应解析 |
| native/models/protocols/responses/{request,stream,response}.py | ResponsesRequestBuilder、ResponsesStreamState、ResponsesResponseDecoder | item/call ID、reasoning items、终态 |
| native/models/protocols/messages/{request,stream,response}.py | MessagesRequestBuilder、MessagesStreamState、MessagesResponseDecoder | signed/redacted thinking、block 闭合、工具结果 |
| native/models/session.py、routing.py、retry.py、usage.py | ModelSessionState、RoutedModel、RetryModel、UsageNormalizer | GA 会话/Mixin 与 WK 请求/重试/usage |
| native/models/tool_protocol/{parser,prompt,adapter}.py | TextToolParser、TextToolPrompt、TextToolModel | GA 文本协议；显式启用与 native 去重 |
| native/hooks/{registry,dispatch,transforms}.py | HookRegistry、LifecycleDispatcher、ContextTransformChain | GA register/unregister/trigger 与 typed 兼容 |
| native/recovery/{snapshot,codec,resumer}.py | RunSnapshot、SnapshotCodec、RunResumer | WK PendingRound/BlockedIndex/消费状态 |
| tools/registry/{definition,context,registry}.py | RegisteredTool、ToolContext、ToolRegistry | 定义/调用上下文/注册分开，__init__ 仅导出 |
| tools/execution/{invocation,scheduler,projection}.py | ToolInvoker、ToolBatchScheduler、ResultProjector | GA 普通/生成器；WK 读并发/写屏障及公开结果 |
| tools/gateway/{ports,authorization,gateway}.py | ToolAccessPort、ToolAuthorizer、AuthorizedToolGateway | 当前授权、风险/审批、执行生命周期明确分层 |
| platform/memory/{service,repository,publication}.py | MemoryService、MemoryRepository、MemoryPublisher | GA 长期记忆/SOP 的读取、整理、索引与版本治理 |

每个主要业务类拥有明确模块；同一领域的小 DTO 可以就近组织，不为满足“一类一文件”制造空包装类。不得将两种协议的状态仍混在 ProtocolState，或把所有实体、服务、工具实现放入一个文件。只有运行成功的完整功能才创建对应目录；上表不是批量创建空文件的任务。

## 端到端执行流程

API 身份与空间校验→应用服务提交并冻结配置/权限快照→同事务写 Run/Outbox→worker claim/lease→ExecutionPreparer 复核当前授权与配置→NativeEngine facade→RunOrchestrator→TurnExecutor→上下文/模型/工具→DurableRuntimeStore 持久消息/事件/检查点→SSE 重放。

等待输入或审批时保存版本化快照和已完成调用记录后释放 worker。恢复先校验快照版本、会话/空间/主体、Agent/模型版本、资源授权、审批消费与已完成 invocation，再从 blocked index 继续；不依赖上次进程的锁、回调、SDK handle 或临时资源短句柄。未知副作用维持 interrupted，不能因重试 lease 就重放。

协议私有历史使用有来源 namespace/version 的可序列化材料，由 Runtime adapter 验证并按已授权会话存储；signed thinking 原文与可读摘要分开，不把 SDK 对象塞入 core 或跨模型无条件回传旧签名。具体字段、大小/保留策略与数据库增量在该模块深读关卡定稿，未定稿前不得实施跨包契约。

## 两项目冲突与拟采用行为

| 冲突 | 实际来源行为 | 拟采用方案及验收 |
| --- | --- | --- |
| 无工具完成 | GA no_tool 可能澄清大代码块或退出；WK 自然停止判断且空文本重试 | 统一决策表，保留 GA 澄清和 WK empty/truncated/filter；保留 Nexus 明确失败码，不将无工具一律成功 |
| 终态/取消 | GA done 消息也可能表示异常结束；WK 有 completion 通知、fallback 和取消保存分支 | 平台唯一 run terminal，终态通知不等于成功；取消保留已发生步骤，不再请求模型生成“成功”答复 |
| hooks | GA 返回 dict 只影响回调链，循环忽略返回值；可原地改对象，终止回合跳过 turn_after | 原始顺序进入兼容测试；对外 typed before/after 总能清理，变换仅管理授权上下文，差异显式记录 |
| 回合计数 | GA 空响应占回合；WK empty retry 可不推进 CurrentRound，另有独立 guard | 区分逻辑 round/模型 attempt/恢复预算，持久累积，不以重新计数绕过 token/耗时限制 |
| 指令时序 | GA 回合末读取 intervene；WK 压缩后/模型前及结束边界 drain | 保留两个安全边界，按持久队列严格顺序消费；写入失败不让后续指令越过，结束前再检查 |
| 摘要与工作记忆 | GA summary/key_info/history；WK compaction checkpoint/usage 校准 | 分别实现，保留源记录；一次性 overflow recovery 不重放已完成工具，失败不保存残缺摘要 |
| 工具并发 | GA 默认顺序；WK 受限读并发、变更屏障、结果按原序 | 默认顺序；显式安全读才并发，未知/写/执行形成屏障，异常隔离与已完成结果保留 |
| 动作授权 | 资源共享与 WK AgentGrant 不同；当前仅一回一审批 | 资源授权保留；独立 ActionGrant 支持 session scope、binding/risk/expiry/revocation，automation 元数据保留到其阶段，不暗开自动化 |
| 记忆/SOP | GA 直接文件 patch；现有平台草稿/审核/版本 | 复用真实整理规则、分层索引和读写算法，经草稿/验证/发布适配，完整实现后才计完成；不改宿主共享 memory |
| 模型切换/配置 | GA 原地搬历史/热配置；平台 AgentVersion/Session 固定 | 保留用户的切换和历史连续性，通过显式模型分支与可追溯版本；协议私有材料按兼容性处理 |
| 上轮已修复模型问题 | GA/WK 部分分支宽松；现有终态与用量局部修复有已确认差异 | 继续以已发布 model-terminal-consistency 规格回归，深读后新增变化另记，不能重新引入 failed→stop 等问题 |
| 宿主执行 | GA 文件/代码/浏览器工具有宿主能力，沙箱仍被用户暂缓 | 全部分析并登记；不在该提案中解除暂缓或把模拟后端计为可用能力 |

## 配置、API 与兼容替换

保留现有个人/空间模型配置、凭据写入方式、AgentVersion 和 Session 固定版本、Run 幂等键、事件 sequence/游标、API 路径和旧 Python 导入。新普通用户行为配置由既有 Native 设置入口及服务端版本快照承载，部署基础配置例外保持文档化；新授权/恢复数据先完成规格、授权与迁移设计。前端更新按原 Vue/Element Plus 职责拆分，不堆入聊天页面或单个 composable。

结构先行：同 schema 移动实体/仓储并跑回归，再分模块替换实际逻辑；每批可由 Git 回退，不引入对普通用户可见的“旧/新内核”部署开关。数据升级与旧快照加载有明确版本转换或受控拒绝，不能默默丢弃。

## 验证与完成标准

每个迁移条目必须具备源码定位/哈希、逐分支映射、目标实现、原测试对应断言、正常/异常/取消/恢复证据。测试执行真实迁移模块，不能只复写 simulate 函数证明概念。模型传输夹具只证明协议分支，不能代替在线供应商；SQLite 不能代替 PostgreSQL 并发。

新增结构验收：导入兼容、单一 SQLAlchemy metadata、现有表/约束不变、无领域反向依赖、__init__ 无业务实现、协议状态分开、主要业务类职责与测试边界明确；不以文件数量或行数上限替代设计审查。

每批运行相关 Python/API/迁移/worker 测试。涉及用户交互时使用 ui-ux-pro-max 并运行前端 build/browser；平台跨空间、撤权、重复投递、崩溃恢复、停止、输入/审批消费与模型错误不得回退。真实供应商、Go 原测试和 PostgreSQL 分开报告未验证边界；沙箱继续暂缓。只有约定核心实现与各类证据完成后才归档，不能先勾选全面深读或完整兼容。
