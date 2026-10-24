# ADR-0003：Native 模型协议与持久执行

- 状态：已采纳；SQLite 与模拟模型验收，PostgreSQL/真实供应商验收待目标环境执行。
- 日期：2026-10-25
- 范围：已批准的 P2 Native 闭环

## 决策

- Native Engine 独占模型/工具循环；worker 装配模型、工具网关、持久化与取消信号，不再套执行循环。旧 `AgentRuntime` 契约保留，新契约集中在 `nexus_core.runtime`。
- 首个模型适配使用 `openai==2.29.0`（Apache-2.0）的异步 Chat Completions 流。模型配置必须显式设置 `options.protocol=openai_chat_completions`；`provider` 名称不用于猜测协议。SDK 类型与异常只在模型适配器中出现。禁用 SDK 自动重试，工具执行后不重放整个回合。
- 工具参数使用 `jsonschema==4.26.0`（MIT）校验，定义按名称和版本注册；处理器必须为可协作取消的异步函数。阻塞或资源密集执行需独立 executor/隔离后端，不能当作普通快速函数注册。
- 工具由显式绑定和当前资源授权共同控制；模型不能通过参数选择主体/空间/Run。工具作者提供公开结果投影；投影后的最多 4000 字符用于模型、消息和事件，原始输出不自动落盘。详细输出/文件产物留待隔离 Artifact backend，不把截断伪装成完整结果。
- 凭据仅在 worker 边界解析。首个 resolver 读取 `env://` 引用，并额外要求 `NEXUS_MODEL_CREDENTIAL_ALLOWLIST`；默认拒绝所有环境变量名。其他凭据后端保留注入端口。
- 同一 Session 仅允许一个活跃 Run（含等待状态），由服务检查和数据库部分唯一索引兜底。重复幂等请求仍返回同一 Run。
- 等待输入继续同一 Run：持久问题与回答，重置该 Run 的 execute Outbox 后释放请求。回答幂等，轮次/token/活跃耗时预算累计，用户等待时间不消耗执行时长。
- 不恢复进程内模型流。失去 execute 租约后 Run/未决工具标记 interrupted；旧 worker 的持久化写入检查租约，不盲目重放副作用。
- SSE 使用 sequence 作为 `id` 和 `Last-Event-ID` 游标，JSON 保留独立 `event_id`。先提交事件后读取投递；每页最多 500 条。浏览器连接不负责执行。
- 上下文优先完整保留最近的消息/工具交换，较早内容压缩为明确标注的局部原文摘录。原消息不删除，记录 `context.compacted`；仍装不下则显式 `model_context_exceeded`。供应商未报告 usage 时按 UTF-8 字节保守估算预算，调用前预留输入预算并限制输出，不声称精确计费。
- 工作检查点按 Session 保存；Memory/SOP 仅创建带来源、作用域和 diff 的 `pending_review` 草稿，不自动注入后续 system prompt。审核、发布和长期检索治理仍是后续能力。
- 没有已验收的隔离后端，不注册任意代码、shell、宿主文件或任意网络工具；`SandboxPort` 保留契约，能力接口明确 unavailable。

## 迁移与兼容

P2 在 P1 后新增迁移 `b5a16ed22801`，为消息增加内部 Runtime 元数据，并新增预算、输入请求、检查点和草稿表。原事件结构和 JSON 分页接口保留；SSE 通过 `Accept` 协商。

升级前，已有库若同一 Session 存在多个活跃 Run，新增唯一索引会拒绝迁移。需先逐项取消/完成旧任务，不能通过清表或自动改写用户任务绕过约束。SQLite 仅作为隔离测试，不作为 PostgreSQL 并发验收证据。

## 依据与归属

- [OpenAI Python 官方文档](https://developers.openai.com/api/reference/python)
- [Chat Completions 流事件](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events)
- 依赖准确版本与间接依赖见 `uv.lock`；浏览器验收使用 `playwright==1.58.2`（Apache-2.0），见前端锁文件。
- 只读核对 GenericAgent `a9a36b4`（MIT）和 WeKnora `e1f9a6166`（MIT，含其第三方许可说明）；未复制参考项目源码。行为映射与验证证据见 [P2 验收记录](../../openspec/changes/p2-native-agent/verification.md)。
