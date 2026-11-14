# Hyoga Nexus 架构

本文件包含两部分：**1. 总体设计**与 **2. 模块设计**。实施顺序、状态与验收见 [roadmap.md](roadmap.md)。

---

## 1. 总体设计

### 1.1 架构原则

- **平台与运行时分离**：平台掌握身份、空间、授权、审批、事件与审计；Native、Codex、Claude Code 只是执行器，共用同一套契约。
- **授权在执行时复核**：每次工具调用、检索和资源读取都重新查询数据库，不信任快照、模型参数或技能声明。
- **事件先持久化再推送**：所有 Runtime 输出统一为 `RunEvent`；只有明确的 `completed` 才是成功。
- **参考项目借鉴设计，按职责拆分实现**：每个模块的借鉴来源与取舍见第 2 节；不嵌入整个第三方项目，不保留参考项目的超大单文件结构。
- **不确定即显式失败**：结果未知的执行标记为 `unknown` 并阻塞会话，直到显式解除，不自动重放有副作用的工具；未验证的能力标记 `unverified`，不对外宣称可用。

### 1.2 总体结构

```text
        Web 工作台 / IM 渠道
                  │
                  ▼
            API 应用服务
                  │
                  ▼
  platform：身份 / 空间 / 授权 / 智能体版本 / 会话 / 运行 / 审批 / 审计
                  │
                  ▼
            Runtime Router
          ┌───────┼────────────┐
          ▼       ▼            ▼
   Native Engine  Codex      Claude Code
                  Adapter    Adapter
       │            │            │
       │            └─────┬──────┘
       │                  ▼
       │        平台 MCP 服务（仅已授权工具）
       │
       ▼
  ToolGateway（授权工具网关）
       │
       ▼
  工具 / 技能 / 知识库 / 记忆 / 观澜工具

  Codex、Claude Code 的原生 shell/文件 ⋯⋯⋯⋯ 受控工作区 / 沙箱
  ToolGateway ─────────────────────────────▶ 受控工作区 / 沙箱

  Native / Codex / Claude Code ─▶ 统一 RunEvent ─▶ PostgreSQL（事件 / 调用 / 审批 / 审计）
                                                └─▶ SSE 续读
```

**进程与存储**：默认（`[deployment].mode = "split"`）API 与 worker 是两个进程；`embedded` 模式下 worker 线程运行在 API 进程内，事件通道用进程内 memory，不需要 Redis，适合本地与小规模部署（见 2.12「实时事件通道」）。多租户部署使用 PostgreSQL 作为事实源，Outbox 派发。单机部署使用单个 SQLite 文件作为事实源，两个进程共用该文件；写入使用 `BEGIN IMMEDIATE`，派发使用同一套账本规则（见 2.12）。两种部署的执行模型相同（见 2.2）。

### 1.3 包职责与依赖规则

| 包 | 职责 | 边界 |
|---|---|---|
| `core` | 标识、端口、DTO、事件、错误码、运行时契约 | 不依赖其他本地包或厂商 SDK |
| `platform` | 身份、空间、智能体版本、资源绑定、会话、运行、队列、凭据引用、授权、审计 | 编排公共服务；不导入 `guanlan` |
| `runtimes` | Native 引擎与外部适配器 | 厂商 SDK 类型不出适配器边界 |
| `tools` | 工具定义、注册、授权网关、通用内置工具 | 领域工具属于领域包 |
| `skills` | 技能发现、解析、版本、依赖、来源检疫 | 技能只描述流程，不授予权限 |
| `mcp` | MCP 客户端、服务端、按工具暴露 | 不默认开放整个服务 |
| `memory` | 记忆规则：草稿审核、版本、归档、有界索引；经存储端口访问数据 | 只依赖 core，不导入数据库或平台包；写入带来源与作用域 |
| `knowledge` | 文档、解析、分块、索引、检索、引用 | 全 Python；不与记忆或结构化行情数据混用 |
| `sandbox` | 执行后端接缝、工作区、租约、产物 | `local` 只用于显式开发模式 |
| `connectors` | 渠道消息标准化与投递 | 不复制智能体循环 |
| `guanlan` | 股票数据、研究、回测、领域工具 | 通过公共协议注册工具和技能 |

`apps/` 是组合根：`api` 装配 HTTP，`worker` 装配后台任务与 Runtime，`web` 提供交互。领域扩展由入口显式注册。

### 1.4 目录结构

```text
hyoga-nexus/
├── apps/
│   ├── api/src/nexus_api/           # FastAPI 入口、http、schemas、dependencies
│   ├── worker/src/nexus_worker/     # 后台入口、jobs、Native 装配
│   └── web/                         # Vue 3 + TDesign，pnpm workspace（core、workspace、admin）
├── packages/
│   ├── core/src/nexus_core/         # 公共协议、runtime、events、tools、tasks
│   ├── platform/src/nexus_platform/ # identity、tenants、authz、agents、sessions、runs、
│   │                                # resources、models、jobs、persistence、observability（memory 门面与仓储）
│   ├── runtimes/src/nexus_runtimes/ # native（context、engine、hooks、models、prompts）、adapters
│   ├── memory/src/nexus_memory/     # ports（存储端口）、service（规则）
│   ├── tools/src/nexus_tools/       # registry、gateway、builtins
│   ├── skills/src/nexus_skills/     # loader、registry、versions、bindings、guard、projection、review
│   ├── mcp/src/nexus_mcp/
│   ├── knowledge/src/nexus_knowledge/ # ingest、index、retrieval、evidence、graph、persistence、domain、providers
│   ├── sandbox/src/nexus_sandbox/   # backends（local、docker）、contracts、artifacts
│   ├── connectors/src/nexus_connectors/
│   └── guanlan/src/guanlan/
├── skills/                          # 技能指令与资源内容（不是实现代码）
├── configs/                         # 非敏感示例；nexus.toml 为本地忽略文件
├── migrations/                      # platform、knowledge、guanlan 的 Alembic
├── tests/                           # 软件测试
├── evals/                           # 智能体、检索、技能、观澜评估样例
└── docs/                            # architecture.md 与 roadmap.md
```

---

## 2. 模块设计

### 2.1 运行时契约（core）

借鉴：DeepSeek Harness `packages/core/agent-loop`（事件溯源、能力接缝）；Hermes（执行后端接缝）。取舍：自研契约，不依赖厂商 SDK。

```python
class AgentRuntime(Protocol):
    def describe_capabilities(self) -> RuntimeCapabilities: ...
    async def start(self, request: RunRequest, ctx: RunContext) -> RuntimeHandle: ...
    def stream(self, handle: RuntimeHandle) -> AsyncIterator[RunEvent]: ...
    async def respond(self, handle: RuntimeHandle, decision: ApprovalDecision | UserInput) -> None: ...
    async def cancel(self, handle: RuntimeHandle, reason: str) -> None: ...
    async def resume(self, snapshot: RunSnapshot, ctx: RunContext) -> RuntimeHandle: ...
```

- `RunRequest`：run_id、session_id、agent_version_id、用户消息、附件引用、模型配置引用、已解析的资源清单（只读快照）、预算、工作区句柄、凭据句柄（不含明文）。
- `RunContext`：主体、空间，以及每次工具调用时重新查询授权的校验函数。
- `RuntimeCapabilities`：每项取值 `supported | unsupported | unverified`，包括 `text_stream`、`tool_bridge`、`mcp`、`skills`、`approvals`、`cancel`、`conversation_resume`、`execution_resume`、`steer`、`native_shell`、`native_file_write`、`network_control`。能力按安装版本和当前配置验证。

**统一事件（RunEvent）**：`run.started`、`message.delta`、`message.completed`、`reasoning.summary`（可选，默认不展示原文）、`tool.started`、`tool.completed`、`approval.requested`、`approval.resolved`、`input.requested`、`artifact.created`、`usage.updated`、`run.completed`、`run.failed`、`run.cancelled`、`run.interrupted`。

- 事件先持久化后推送；同一 Run 内 `sequence` 单调递增；`event_id` 全局唯一。
- 进程退出、连接断开或流结束但无终态，归为 `interrupted` 或 `failed`。
- 有副作用的工具结果未知时，执行记录标记为 `unknown`，会话阻塞，不自动重放（见 2.12 派发账本）。

**终态映射**：

| 统一状态 | Codex app-server | Claude Agent SDK | Native |
|---|---|---|---|
| completed | `turn/completed`，`status=completed` | 结果消息且无错误（实施时核对） | `StepOutcome` 完成 |
| interrupted | `turn/completed`，`status=interrupted` | 取消确认（实施时核对） | 取消已生效 |
| failed | `turn/completed`，`status=failed` | 错误结果（实施时核对） | 异常或预算耗尽 |
| 工具 declined | commandExecution/fileChange 最终 `declined` | 权限拒绝（实施时核对） | 网关拒绝 |

### 2.2 Native 引擎

借鉴：GenericAgent `agent_loop.py`（循环形态、StepOutcome、坏调用恢复）；WeKnora `engine.go`（完成判断、守卫）与 `suspend.go`（挂起恢复）；OpenClaw `run-loop.ts`（外层恢复与预算伸缩）；Dify `fc_agent_runner.py`（最后一轮禁用工具）；n8n `executeBatch`（动作产出与执行分离）；Octop `agents/middleware/model_failover.py`（健康感知故障转移）、`agents/settings/runtime_limits.py`（智能体运行参数映射到运行时）、`gateway/steer/`（运行中追加指令）；octop-harness（`compaction.py` 与 `middleware/summarization_limits.py` 压缩时不重发超大历史、`middleware/tool_order.py` 稳定工具顺序以复用提示缓存、`middleware/model_retry.py` 重试策略、`middleware/model_settings.py` 生成参数、`middleware/conversation_mode.py` 回合级工具白名单、`usage.py` 与 `context_usage.py` 用量归一与上下文占用、`protocols/think_splitter.py` 流式拆分思考内容）。取舍：拆为独立组件，不保留单文件循环。

```text
RunOrchestrator     生命周期、取消、预算、事件持久化、租约检查
 └─ TurnExecutor    单回合：组装上下文 → 调模型 → 解析结果
     ├─ ContextAssembler   冻结系统前缀 + 历史视图 + 工作检查点 + 证据句柄
     ├─ ModelPort          流式、厂商无关；SDK 类型只在适配器中
     ├─ CompletionJudge    无工具 / 截断 / 空响应 / 重复内容判断
     └─ ToolDispatcher     schema 校验 → 授权网关 → 执行 → 结果投影与 Spill
```

- **回合结果**：`ToolResult(data, next_prompt, disposition)`，disposition ∈ {`continue`、`complete`、`wait_input`、`exit_failed`}。`exit_failed` 必须带原因，不能用空提示推断成功。
- **完成判断**：无工具且内容非空即完成；长度截断可按预算续写；空响应有限次重试（计入预算）；同一内容重复出现判为停滞；工具调用不完整则不执行，交给坏调用恢复。
- **最后一轮**：达到最大步数时禁用工具，仍请求工具则以明确错误结束（参考 Dify）。
- **预算**：逻辑回合、模型尝试、活跃耗时（不含等待用户时间）、token 四个维度分别计数，持久累计，恢复后继续累计。
- **上下文**：系统提示与工具 schema 在 Run 开始时计算一次，Run 内不变，保护供应商提示缓存（参考 Hermes 冻结快照）。历史是事件流，模型可见消息由事件派生（参考 DeepSeek Harness）。压缩结果作为新事件写入，源事件保留。处理方式参考 LobeHub `context-engine` 的可组合处理器与 WeKnora `compaction/`；证据句柄登记参考 RAGFlow `evidence_registry`。
- **压缩**：优先完整保留最近的消息与工具交换；较早内容压缩为标注过的局部摘录；仍装不下则显式失败 `model_context_exceeded`。压缩带滞后：只在历史超过 `compact_high_ratio × max_context_chars` 时触发，目标为 `compact_low_ratio × max_context_chars`，两者之间不重复压缩。摘要长度不超过 `summary_max_chars`。摘要可由 `compaction_model_profile_version_id` 指定的模型生成，每次摘要调用都重新授权；该模型不可用时降级为确定性摘录并记录 `context.summary_degraded`，Run 继续。
- **工具结果视图**：超过 `tool_result_window_rounds` 次模型调用之前的工具结果，在发给模型的视图中替换为单行索引（工具名与首行）；源消息不变。超过 `tool_output_inline_limit` 的输出外置，见 2.5。
- **工具顺序**：同一回合内按模型声明顺序执行，每个调用独立记录 invocation；有副作用的工具之间不并发。工具声明为只读且幂等（`read_only`、`idempotent`，且无副作用、无需审批）时，可在 `parallel_reads` 开启下与相邻只读调用并行；结果仍按模型声明顺序返回。只读声明与副作用冲突时注册即拒绝。
- **取消与等待**：取消信号在模型流、工具和沙箱调用的每个等待点检查；`ask_user` 类工具产生 `wait_input`，释放 worker，回答后在同一 Run 中幂等继续。
- **运行监督（Watchdog）**：执行期间的监控协程按 `[watchdog].interval_seconds` 调用 `DurableRuntimeStore.watch`，只检查 `running` 的 Run：长时间无新事件（`idle`），或最近 `repeat_threshold` 次 `tool.started` 的工具名与参数摘要相同（`repeat`）。命中时追加 `run.watchdog_alert`，同一规则在一次停滞期内只报告一次；Watchdog 不取消、不重试、不修改 Run 状态。检测失败只记日志，不影响 Run。回合数规则依赖预算计数（路线图 3.15），尚未实现。
- **执行模型**：每个 Run 新建执行对象（引擎、工具网关、运行上下文），Run 结束即释放；不按会话缓存执行对象。工具注册表是进程级共享对象（定义不含 Run 状态，存储经 `ToolContext.services` 按调用传入）。模型客户端每 Run 构建，凭据每 Run 解析并只用于该次调用；进程内按来源共享 HTTP 连接池（不含凭据），地址校验仍逐请求执行；池的上限由 `configs/nexus.toml [model_connection_pool]` 配置（`max_connections`、`max_keepalive_connections`、`keepalive_expiry_seconds`，缺省与 httpx 默认值相同），worker 启动时生效。worker 使用单一事件循环，连接池只在创建它的循环中使用。参考 deer-flow 与 dify-agent。
- **会话状态**：会话状态是版本化的 JSON 快照（v2，只含数据，不含配置、客户端、租约句柄、令牌或模型对象）。Run 结束时（成功、失败、取消均要）在 `finally` 中保存终态快照；未执行的工具调用标记为 `interrupted`，使下一轮历史合法。快照读取失败、版本未知或状态损坏时拒绝该 Run，不静默丢弃历史。
- **恢复**：恢复前校验快照版本、会话/空间/主体、Agent/模型版本、资源授权、审批消费状态与已完成的 invocation，再从挂起点继续。不依赖进程内锁、回调、SDK 句柄或临时资源。进程崩溃后，上一代际未完成的执行转为 `unknown`，会话阻塞，需显式解除（见 2.12）。
- **钩子**：agent/turn/model/tool 的 before/after 类型化钩子，只接收稳定元数据 DTO，不暴露 locals、SDK 对象或凭据；异常隔离，超时忽略。
- **Run 状态**：queued、running、waiting_input、waiting_approval、completed、failed、cancelled、interrupted。同一 Session 同一时刻只执行一个 Run（running、waiting_input、waiting_approval），由派发账本的队首领取与数据库部分唯一索引共同保证。忙时提交的 Run 为 queued，按 FIFO 等待（见 2.12）。

### 2.3 Codex 适配器

借鉴：Hermes `codex_app_server.py`（JSON-RPC over stdio、initialize 握手、版本门槛）；官方 `openai-codex` SDK 与 App Server 文档（实施时重新核对）；octop-harness（经 ACP 委派外部编程智能体：`acp/` 客户端、服务与权限处理，`builtin/tools/acp_runner.py` 委派工具）。

- **集成方式**：SDK 负责进程与基础调用；流式事件与审批经 app-server 协议获取。
- **通道前提**：若 SDK 暴露底层 JSON-RPC 通道，事件、审批与 SDK 调用共用一个连接；若不暴露，则直连 app-server 协议，SDK 仅用于 CLI 版本锁定。该前提的确认结果记录在路线图中，方案变更须通过变更提案确认。
- **版本**：SDK 与 CLI 版本一并锁定；启动时读取版本与 `initialize` 能力，不匹配则能力标记 `unsupported`。
- **会话**：平台 `session_id` ↔ Codex `thread_id`，记录在 `runtime_session_bindings`。`thread/resume` 恢复，`thread/fork` 分支，`thread/compact/start` 仅在平台压缩不可用时使用。
- **事件映射**：`item/agentMessage/delta` → `message.delta`；`item/started` / `item/completed`（命令、文件变更、动态工具）→ `tool.started` / `tool.completed`；审批请求 → `approval.requested`，平台决定后回复 `accept` / `acceptForSession` / `decline` / `cancel`；`acceptForSession` 必须先经 `action_grants` 批准；`thread/tokenUsage/updated` → `usage.updated`；`turn/completed` → 终态映射表。
- **取消**：`turn/interrupt`，收到 `interrupted` 终态后才结束 Run。`turn/steer` 默认 `unsupported`。
- **原生能力约束**：文件与 shell 通过 `Sandbox` 参数限制为 `workspace_write`，工作目录为平台分配的隔离工作区；多用户场景禁止 `full_access`。无法验证网络控制时能力标记 `unverified`，禁止绑定需要网络控制的技能。
- **平台工具**：经平台 MCP endpoint 暴露，外部客户端以 endpoint 长期令牌鉴权、只读白名单工具面；平台复核权限，不信任模型传入的 tenant 或 user 标识。
- **传输**：只使用 stdio。WebSocket 为实验性，启用前必须配置鉴权。`-32001` 过载错误使用指数退避与抖动，并计入预算。

### 2.4 Claude Code 适配器

借鉴：官方 `claude-agent-sdk`（无开源参考实现）；octop-harness `acp/`（经 ACP 委派 Claude Code，仅参考协议形态）。实施前须读官方文档并锁定版本，未核对的行为保持 `unverified`。

- **集成方式**：`ClaudeSDKClient`，支持自定义工具与 Python 回调钩子。
- **权限**：`can_use_tool` 回调作为审批入口，映射到 `approval.requested`。`allowed_tools` 只做自动批准、不隐藏工具，因此禁用原生工具必须用 `disallowed_tools`。
- **会话**：首次回复记录 session id；后续 `resume`；`fork_session` 用于分支。
- **系统提示**：SDK 在首次请求记录并复用，平台提示变化只在新会话生效。
- **原生工具**：Bash、Edit、Read 等必须通过 `disallowed_tools` 或 `can_use_tool` 限制；无法限制的工具不允许绑定到该 Runtime。
- **依赖**：本机需安装 Claude Code CLI，版本与 SDK 配套；账号与模型权限单独验证。

**切换规则（两种外部 Runtime 共同适用）**：切换 Runtime 时创建新会话或显式分支。平台将摘要、已授权消息与引用传给新 Runtime，不承诺迁移 SDK 内部状态。能力不足时界面显示差异；发布智能体时拦截不满足其绑定资源的组合。

### 2.5 工具与授权网关

借鉴：GenericAgent `ga.py`（`do_*` 分发、输出限制）；DeepSeek Harness `spill`（大输出落盘）；WeKnora `tools/` 与工具策略（每次调用复核）；Octop `agents/settings/tool_catalog.py`（工具目录与禁用策略）；octop-harness `middleware/tool_guard.py` 与 `security/tool_guard/`（执行前扫描工具参数）、`middleware/tools_filter.py`（对模型隐藏禁用工具）、`middleware/tool_order.py`（稳定工具顺序）。取舍：网关只能收紧权限；模型不能选择主体。

- **定义（ToolDefinition）**：名称、版本、JSON Schema（参数与结果投影）、风险等级、所需资源、副作用标记、幂等性标记、超时、所需 capability。
- **注册**：按名称与版本登记。处理器必须可协作取消；阻塞或资源密集的函数需要独立执行器或隔离后端。
- **ToolGateway（单调守卫）**：每次调用依次经过 schema 校验、当前授权查询（查数据库，不读快照）、风险分级、审批（如需）、执行、结果投影、审计。守卫只能收紧权限；模型不能通过参数选择主体、空间或 Run。
- **结果投影与 Spill**：工具作者提供公开结果投影。未绑定 `read_tool_output` 时，结果最多 4000 字符进入模型与事件并截断。绑定后，超过 `tool_output_inline_limit` 的公开结果写入 Run 级 `tool_outputs` 表，模型只看到预览与句柄；`read_tool_output` 按句柄与 offset 分页读取，只能读取同一 Run 的输出，每次读取写入审计。引擎在视图层裁剪更早的工具结果（只改模型视图，不改源消息）。截断与外置必须显式标注。
- **内置工具**：平台类（知识检索、记忆读取、检查点、待办、询问用户）；领域类（观澜，由领域包注册）；受控执行类（代码、文件、Web），仅在沙箱后端通过验收后开放（见 2.9）。
- **工具分组与门控**（提案 `openspec/changes/2026-11-07-tool-expansion`，实施中，设计见 `packages/tools/docs/design.md`）：每个工具声明 `group`；工具组出现在 Run 里需要两层同时满足——部署侧可用（沙箱通过验收、`[web].enabled`、绑定了 Wiki 库……）与智能体开关（`tool_groups_enabled`，高影响组默认关闭）。门控只收紧，授权、访问级别、守卫、审批照常。调度按调用声明 `parallel` / `exclusive` / `serial(key)`；可能进入审批的调用一律独占。绑定工具的 schema 过大时，MCP 等可延迟工具改经 `tool_search` / `tool_describe` / `tool_call`，Run 内工具块不变。
- **协作与定时**：`delegate_task` 在进程内嵌套一个 Run，工具集是父级的子集且不含 `collab`，需审批的操作被拒绝，用掉的 token 计入父级；`cronjob_*` 创建的任务以所有者身份在固定智能体版本上无人值守运行，没有提问与审批，每人最多 10 个活动任务，最短间隔 15 分钟。
- **定时任务的管理界面**：`/api/v1/tenants/{id}/schedules` 提供列表、创建（选一个已发布智能体，固定其当前已发布版本，创建后不能换）、详情、修改（名称、提示词、规则、时区）、暂停 / 恢复 / 删除、立即运行（不改下次触发，60 秒内限一次）、任务会话的运行记录与触发预览；规则仍只有每 N 分钟、每天、每周一天。默认只管理本人的任务，空间 owner / admin 可用 `scope=all` 查看全部并暂停他人的任务，不能改内容、恢复、删除或运行。前端 `/platform/automations` 复用 WeKnora 自动化页，经 `nexusAutomationAdapter` 把 Nexus 任务转成其数据形状：触发器只接受与三种规则一一对应的 cron 形式（`@every Nm`、`M H * * *`、`M H * * D`），其余调度类型、重叠与漏触发策略、授权、通知在界面标「待实现」。
- **工具调用加固**（提案 `openspec/changes/archive/2026-11-06-tool-call-hardening`，已实施，设计见 `packages/tools/docs/design.md`）。借鉴 WeKnora `registry.go`、`param_cast.go`、`json_repair.go`、`truncate.go`、`policy/`；hermes `arg_coercion.py`、`agent/tool_guardrails.py`、`enforce_turn_budget`、`approval_floors.py`、`threat_patterns.py`；octop-harness `tool_guard`、`tool_order`；deepseek `repeat-tool-reminder`。
  - 执行顺序：授权 → 访问级别判断 → 参数预处理（JSON 修复、按 schema 保守转换类型、校验并返回字段级错误）→ 参数守卫 → 审批（会话放行只覆盖访问级别和 `requires_approval` 带来的审批）→ 执行 → 注入扫描 → 外置（计入每轮总预算）→ 头尾截断。
  - 工具定义按名称排序；风险改为 `read` / `probe` / `write` / `destructive`，智能体访问级别 `read_only` / `standard`（默认）/ `strict`。
  - 参数守卫：随包规则（字段沿用 octop-harness YAML，以 JSON 存放），`CRITICAL` 硬拒绝（任何放行都不能绕过），`HIGH` 必须审批，`MEDIUM` 只记录。
  - 循环检测在引擎侧：相同（工具、参数、结果）或周期 2–4 的循环先提醒，达到阈值以 `tool_loop_detected` 结束 Run。

### 2.6 技能（Skill）

借鉴：Hermes `skills_guard.py`（来源检疫）、`skills_hub`（来源与安装）；DeerFlow `skills/`（projection 沙箱只读投射、security_scanner、mutations 审核修改）；octop-harness `skills/catalog.py`（扫描技能目录）、`middleware/skill_filter.py`（智能体级禁用与按请求过滤）。取舍：技能不授予权限；发布需审核。

- **定义**：版本化的 `SKILL.md` 加资源文件，描述工作流程、何时调用哪些工具、输出格式。**技能不授予任何权限**。
- **版本**：SkillVersion 不可变，保存正文、资源、依赖（工具、MCP 工具、知识库）与内容哈希。草稿可改，发布生成新版本。
- **渐进披露**：默认只向模型提供名称与简介，正文按需加载，资源按需读取。
- **依赖校验**：发布智能体版本时检查技能依赖是否已由智能体绑定满足；缺失则拒绝发布并说明原因。
- **来源检疫**：内置技能可信；其余按来源（`admin` / `import` / `agent` / `user` / 私有）与规则扫描结论（`safe` / `caution` / `dangerous`）查放行矩阵：`admin` 遇 `dangerous` 须显式确认并审计；`import` 遇任何发现阻止，管理员可留理由放行；`agent` 与 `user` 进入共享审核，遇 `dangerous` 拒绝；私有技能遇 `dangerous` 拒绝保存。扫描覆盖可疑网络请求、凭据读取、敏感路径写入、破坏性命令、混淆代码与针对模型的指令覆盖，扫描器带版本号，升级后旧版本标为需重扫。已实现：规则扫描器、放行矩阵、`admin` / `import` / `builtin` 的发布路径、确认放行与审计、重扫；`agent` / `user` 的审核流程尚未实现。扫描只是门禁之一，运行时授权仍然有效。
- **内置技能与工具**：登记在保留的系统租户（`tenants.kind = 'system'`，无成员、不可登录、不出现在任何列表）名下，对所有企业**可见且可分配**（不是自动启用，智能体仍须绑定）；授权对系统租户来源的技能与工具放行，无需授权行；空间管理员可对本空间停用某个内置资源（`tenant_builtin_disabled`），不影响其他空间与已发布的智能体版本。内置技能由平台管理员接口或 `uv run python -m nexus_api.cli import-builtin-skills` 从仓库 `skills/` 导入，内置工具随 API 与 worker 启动同步。
- **脚本执行**：技能脚本是技能目录里的普通文件，不在 frontmatter 声明。`exec_skill(name, script, args?, stdin?)`（`skills` 组）在智能体所选的沙箱档位里运行其中一个脚本：技能文件按内容哈希只读投射到沙箱，`args` 作为参数列表传入、不经 shell 解释，`stdin` 最多 65536 字节，解释器按扩展名或 `#!` 行在 `python3`、`bash` / `sh`、`node` 中选择；运行前校验脚本哈希，审计记录脚本路径与哈希；脚本从 `$NEXUS_SKILL_DIR` 找到自己的文件。需要管道或串联的场景用 `sandbox_exec`（`sandbox` 组）。技能的 `execution` 声明（`sandbox` 默认 / `local`）只是声明：`local` 仅限内置来源且部署开启 `allow_local_scripts`，不满足时不运行，不回退到另一个位置。沙箱档位见 2.9。
- **frontmatter**：`SKILL.md` 的前置块按 YAML（`safe_load`）读取，已知键之外的键保留不拒绝，常见的缩进与冒号问题做保守修复并标记；名字为小写字母、数字与连字符（1–64 字符，不含 `anthropic`、`claude`）；`model_invocable` 为假的技能不进模型的技能索引；`execution` 声明脚本位置，`local` 仅限内置来源。
- **包与安装**：每个版本保存一份规范 zip（排序、固定时间，同内容同字节），二进制文件只存于 zip，运行时与文本文件一起投射进沙箱。zip 经 `nexus_skills.bundle` 先查条目表再按上限读取（拒绝穿越、符号链接、重复路径、加密、压缩炸弹），再做语法验证（`.py` / `.sh` / `.js`）、扫描与放行矩阵。带 `requirements.txt` 或 `package.json` 的版本先是 `installing`，由 worker 在所选档位的临时环境里联网构建依赖，核对清单包后原子换入，再 `ready` 并移动当前版本指针；失败保留 zip 可重试，旧版本继续服务。远程来源（GitHub、GitLab、skills.sh、ClawHub、直链）经 `nexus_core.egress` 受保护下载（只允许公网地址、逐跳校验），仅管理员且必须确认，只比较更新、不自动更新。
- **私有技能与共享**：私有技能属于某个用户，不登记为平台资源、不绑定，该用户的会话自动并入索引。模型用 `skill_manage` 改草稿（先读后写、补丁须唯一匹配、固定子目录、数量与大小有上限），`skill_save` 每次需用户确认且不能「本会话允许」，保存走同一安装流水线，`dangerous` 拒绝；每次保存是新版本，可回退，删除是归档。共享到空间库是**复制**：管理员（`tools:manage`）直接发布，持 `skills:submit` 的成员提交，管理员审核（内容、扫描发现、与库版本的差异）后通过或拒绝（理由必填），通过时重扫并复核库未变化。不得直接修改已发布版本。
- **与 Runtime 的关系**：Native 由平台加载指令与资源；Codex、Claude 将技能转换为指令，或在 SDK 支持时加载技能目录。转换方式在能力表中标明。

### 2.7 MCP

借鉴：WeKnora `approval/mcp_risk.go`（高风险 MCP 工具审批）；Octop `connectors/custom_mcp.py`（自定义 MCP 服务）、`mcp_tool_cache.py`（按用户缓存工具定义与指纹）、`connectors/oauth/`（连接器 OAuth）；octop-harness `middleware/mcp_tools.py`（按请求过滤 MCP 工具）、`middleware/mcp_tool_error.py`（MCP 错误转为失败的工具结果）。

- **客户端**：连接外部 MCP 服务，发现工具，按工具启用，不默认开放整个服务；凭据以引用保存。
- **OAuth**（`auth_type='oauth'`，只用于 HTTP 传输）：授权码 + PKCE（S256），未预置客户端时按 RFC 7591 动态注册并按（租户、服务）复用；令牌按（租户、主体、服务）加密保存，使用前带 30 秒余量惰性刷新。资源服务器 401 恰好一次 refresh + 一次重试；刷新被拒删除令牌并返回 `mcp_oauth_required`，客户端注册被拒同时丢弃动态注册。动态令牌优先于服务级静态 `Authorization` header，`headers` / `env` 的 `credential_references` 路径保留。授权 `state` 为部署密钥加密的短时载荷；回调为公开接口，结果只经 URL 片段回前端。
- **服务端**：无状态 endpoint 把白名单内的只读工具暴露给外部 MCP 客户端（Codex / Claude Desktop / Cursor），不绑定 Run。`tools/list` 返回白名单内的只读定义；`tools/call` 在 API 进程内直接调用平台服务的无状态入口（知识检索 / web / skills / memory / conversations），每次复核工具仍在白名单、endpoint 仍启用、KB 仍在范围，不走 `AuthorizedToolGateway` 与 worker。
- **endpoint 长期令牌**：创建 / 轮换时签发，SHA-256 哈希存储，明文只在签发响应出现一次；撤销即失效。挂载于 `/mcp/{endpoint_id}`，Bearer 鉴权提前于全局会话 Auth，把令牌映射为作用域化主体（机器身份 + 工具白名单 + KB 范围）；解析失败统一返回协议级 `unauthorized`，不泄漏资源存在性。
- **客户端接入约束**（提案 `2026-11-06-tool-call-hardening` 决定 3，随第 7.2 步实现）：
  - 注册名用 `sha256(server_id \0 tool_name)` 加可读前缀，同名先注册者保留（WeKnora `mcp_exposure.go`）。
  - 风险取「工作区显式设置 > 曾观察到的最高声明 > 当前声明」，服务端自行降级需工作区确认（WeKnora `approval/mcp_risk.go`）。
  - 每次执行前复核目录与开关；按用户缓存工具定义，用连接参数指纹判断失效（Octop `mcp_tool_cache.py`）。
  - `McpError` 提示修正参数，输出 schema 失败提示不要改参数重试（octop-harness `mcp_tool_error.py`）。
  - 工具描述带外部数据前缀；按供应商清洗 schema（hermes `schema_sanitizer.py`）；工具较多时用 `tool_search` 渐进加载（octop-harness `tool_search.py`）。
- **高风险工具**：按风险等级要求审批，结果记录为 `action_approvals`。

### 2.8 记忆

借鉴：GenericAgent `memory/`（四层结构、SOP、写入约束）；Hermes `memory_tool.py`（冻结快照、用户画像）；DeerFlow `agents/memory/`（后端无关契约、prescreen 预筛、异步去抖）；TradingAgents `memory/log.py`（决策记录与事后回填）；octop-memory（L0 原始事件 → L1 候选 → L2 原子卡片 → L3 实体页 → L4 审计日志的分层；`pipeline/promotion/checks.py` 候选晋升前的五项检查、`pipeline/recall/` 召回路由、预算、注入前抑制与重排、`domain/retention.py` 按来源的保留规则）。

实现位于独立包 `packages/memory`（规则）与 `nexus_platform.memory`（存储）。

| 层 | 内容 | 生命周期 | 写入规则 |
|---|---|---|---|
| 工作检查点 | 当前任务目标、已完成步骤、待办、关键变量 | Session 内，任务结束后归档 | 只能由成功的工具结果更新 |
| 会话历史 | 消息与工具交换 | Session 生命周期 | 追加；压缩结果作为事件写入 |
| 用户事实与偏好 | 用户画像、长期偏好 | 跨会话，按用户隔离 | 草稿 → 审核 → 发布；会话开始时冻结快照进入提示 |
| 可复用经验（SOP） | 验证过的操作流程与脚本 | 版本化，按智能体或空间共享 | 草稿 → 审核 → 发布，不直接修改生产版本 |
| 原始会话归档 | 历史会话全文 | 长期保存 | 只追加，不参与提示 |

- 所有写入携带来源（Run、事件、工具结果）、作用域（用户/空间/智能体/Session）与版本；不得写入密钥与凭据。
- 写入前预筛：只保留与任务相关、有依据的内容。
- 草稿在审核前不进入任何系统提示；检索与注入只使用已发布版本。
- 记忆层级之间可以迁移（如从归档提炼经验草稿），但不丢失来源。
- 记忆不是知识库：记忆保存偏好与经验，知识库保存可引用的资料。
- 索引：维护短小的导航索引（不超过 30 行）指向条目，不直接存放事实正文（参考 GenericAgent L1）。

**实现要点（阶段一，openspec 2026-11-01-memory-optimization）**：
- 提议经 `nexus_memory.text.screen`：威胁规则（提示覆盖、角色冒充、保留标记、外传指令、不可见字符）命中则整体拒绝；密钥、身份证（校验位）、银行卡（Luhn）、手机号替换为 `【已隐藏】`，审计只记录类别。
- 提议前做指纹去重（已发布条目与待审草稿），并检查墓碑（被拒绝的内容不得再次提出）。预算默认每所有者 6000 字符，超出时返回现有条目列表；编辑草稿携带 `base_version`，发布时仍需匹配。
- 索引只列出启用、未归档、未过期的条目，超限时按行截断并注明省略数量。模型读取的记忆正文以 `<user_memory>` 包裹，内容中的尖括号转义，声明为资料而非指令。
- `search_memory` 为只读关键词检索：查询与正文用二元组分词，要求全部词命中；SQLite 使用 contentless FTS5，建表前探测版本（≥3.43）与模块，不满足或其他数据库时回退为 token 子串匹配。结果只含 ID、标题、版本与片段，正文需 `read_memory`。
- 启停（`enabled`）与有效期（`valid_until`）与归档分开：停用或过期只影响索引与检索，版本保留；HTTP `PATCH /memory/{id}`。
- 会话内快照：每个会话的第一个 Run 冻结所有者的已发布记忆索引，之后的 Run 复用，系统前缀保持稳定。新发布的记忆在用户刷新快照（`POST .../memory-snapshot/refresh`）后才进入该会话。快照只对会话所有者可见。

**实现要点（openspec 2026-11-06-memory-evolution，分阶段实施；第 1–6 阶段与设置页已完成；文档亲和度等待知识检索）**：
- 自动抓取只以用户本人写的消息为来源（按消息来源白名单排除运行时补发的合成消息），助手文字只作只读上下文；每项草稿必须带可校验的原文证据，低价值项不建草稿。
- 抽取模型看到按对话相关性挑选的已发布条目（带编号）和最近被拒的主题；主题或内容与已发布条目相同时生成编辑草稿，冲突只作审核提示。
- 会话快照包含容量行和 `profile` 常驻块（画像正文，不超过 1000 字），其余条目仍是索引；索引与检索按重要度、最近使用和时效排序，读取、命中和常驻注入记录使用统计。
- Run 事件 `memory.used` 记录本轮注入或读取的记忆，对话时间线显示"本次使用了 N 条记忆"；模型提出的草稿发 `memory.draft_proposed`，所有者在对话内的确认卡片中发布或拒绝。空间可设置不超过 1000 字的自定义抽取规则。
- 近似重复的草稿带相似提示；worker 定期（或按用户请求）整理同义记忆，产出合并草稿，发布时保留一条、归档其余；被拒草稿与结束的抓取任务按期清理，审计、版本与墓碑永久保留。
- 历史会话检索：`search_conversations` 按关键词检索本人在本空间的其他会话原文，`read_conversation` 分页读取前后消息；受记忆开关与会话历史授权约束，不经模型摘要。
- 语义召回：空间可选 Embedding 模型，向量存于数据库并在应用内比较，检索时与关键词结果按名次融合，失败退回关键词；每个 Run 按本轮问题注入最多 5 条、600 字的相关记忆，放在最后一条用户消息之前，不改系统前缀、不入消息表。
- 兴趣主题：同一主题在多个会话出现达到空间阈值时提出 `interest` 草稿；外部记忆提供方端口允许每个空间接入一个外部服务，调用有截止时间与失败暂停，写入只能成为草稿。
- 任何路径都不自动发布记忆；后续阶段（常驻画像块、对话内确认、语义合并、历史会话检索、向量召回等）见该提案的 `tasks.md`。

### 2.9 沙箱与执行环境

借鉴：DeerFlow `sandbox/`（lease 租约、虚拟路径、原子写入、文件锁）；Hermes `tools/environments/`（多后端）；DeepSeek Harness（接缝）；FastGPT `agent-sandbox`（容器镜像，仅参考）；Octop `infra/backend/`（工作区后端可插拔：本地、Docker、PostgreSQL、对象存储，与控制面数据库分离）；octop-harness（`backends/docker_sandbox.py`、`backends/bwrap_shell.py` 目录隔离、`backends/local_shell.py` 虚拟路径转换、`backends/composite.py`、`backends/probe.py` 写读删连通探测、`security/ssrf.py` 出站请求 SSRF 防护）；octop-browser（`cdp/` 纯 asyncio CDP 客户端与进程管理、`dom/builder.py` 面向模型的分层 DOM、`profile.py` 会话持久化、`idle.py` 空闲回收、`mcp_server.py` 以 MCP 暴露浏览器操作）。

- **接缝**：`CommandExecutorPort`（命令执行）与 `FileStorePort`（文件读写与产物）。后端：`local`（仅开发模式，不能用于多用户）、`docker`（候选）、`ssh`（候选）。
- **租约**：执行方持有租约，到期或任务结束后回收；超时与取消释放租约。
- **虚拟路径**：模型看到 `/tenant`、`/outputs` 等虚拟路径，宿主路径由后端映射，不泄露宿主结构。
- **文件写入**：临时文件加原子替换；不对并发写入做仲裁。
- **产物**：Run 结束时（不论成功、失败或取消）worker 把 `/outputs` 下的普通文件复制到 `<[sandbox].workspace_root>/_artifacts/<tenant>/<artifact>` 并写入 `artifacts` 表（关联会话、Run 与发起人，记 `sha256`、大小、类型）；符号链接跳过，同会话同路径内容未变不重复登记，单文件 50 MB、每 Run 50 个且 200 MB、每空间 2 GB，超出的跳过并写入 `artifacts.registered` 事件的 `skipped`。接口 `/api/v1/tenants/{id}/artifacts`（列表、详情、下载、删除）：会话所有者看自己会话的，空间 owner / admin 看全空间的，其他人一律不存在；下载以附件、`application/octet-stream` 与 `nosniff` 返回并写审计，登记、下载、删除均有审计。列表支持 `q`（名称）、`extensions`、`latest`（每个文件只取最新版本并带 `version_count`）、`session_id`、`run_id` 并返回 `total`；`DELETE ?all_versions=true` 连同同会话同路径的所有版本一起删。前端 `/platform/artifacts` 复用 WeKnora 的产物库页面，经 `nexusArtifactAdapter` 适配：按产物 id 下载与预览，删除即删全部版本。聊天页在打开会话和每次 Run 结束后读取该会话的产物，按 `run_id` 在对应回复下显示「本次生成的文件」卡片（可预览的类型在抽屉里预览，其余仅下载，超过 4 个折叠）。API 与 worker 需共享该目录（单机或共享卷部署）。
- **实现状态**（提案 `2026-11-07-tool-expansion`，进行中）：`docker` 后端、文件存储、租约、验收与六个 `sandbox_*` 工具已实现，单元测试覆盖；**真实 Docker 守护进程上的验收尚未运行**，在此之前该组对所有智能体不可见。`ssh` 后端、跨 Run 的后台作业结果回投未实现；产物登记、下载接口与产物库页面已实现（页面未在浏览器验证）。
- **门禁**：只有通过隔离验收的后端才能注册任意代码、shell、文件写入工具。验收项：CPU、内存、时间、输出大小限制；网络隔离；用户隔离；清理；崩溃后残留检查。未通过时工具不出现在工具列表中，而不是返回错误。
- **部署环境**：候选后端的部署条件（容器运行时或远程执行环境）待确定。
- **执行类工具约束**（提案 `2026-11-06-tool-call-hardening` 决定 3，随第 8 步实现）：工具可按参数声明能否并行（deepseek `isConcurrencySafe`）；同一路径的写入串行化（WeKnora `file_mutation_queue.go`）；shell 类工具必须经过参数守卫。

### 2.10 知识库

借鉴：WeKnora（功能基线：库类型、索引策略、向量库与存储后端注册、FAQ、Wiki、Neo4j 图谱、数据源）；RAGFlow `internal/agentic_rag/`（证据登记 `[ID:n]`、判断与断路、检索工具正交化）与 `internal/service/graph/`（GraphRAG 检索）；FastGPT（训练队列、同义词）；Dify（元数据过滤、重排）；Octop `infra/knowledge/`（`gate.py` 能力门控、`citations.py` 机器可读引用）。实施提案 `openspec/changes/2026-11-06-knowledge-base`（K0–K7 分阶段）。

**Wiki 库（K6）**：开启 `indexing.wiki` 的库（`type=wiki` 恒开启）在文档 ready 后由 worker 的 `wiki` 任务用创建者的 Key 合成页面：摘要页 `summary/*`、实体页 `entity/*`、概念页 `concept/*`，并维护 `index` 简介页；页面以 slug 为键，`[[slug|名]]` 链接在写入时校验并派生入/出链，每次写入保留修订并带乐观锁；目录（文件夹）由一次分类规划调用复用已有文件夹生成，用户的归类不被覆盖。页面作为索引行（页面 id 充当“版本”）进入库的向量库，与文档共用 Pre-Filter、混合检索与重排；删除文档触发撤回（无来源页面删除，共享页面重写）。接口在 `/knowledge/bases/{id}/wiki`，实现见 `nexus_platform/knowledge/wiki.py`、`wiki_ingest.py` 与 `nexus_knowledge/wiki/`。

**库共享（K1.9）**：库属于所属空间；owner / admin 可把库共享到自己所在的共享空间（`knowledge_base_shares`，级别 viewer / editor / admin，与智能体共享同一套有效级别规则：共享级别、成员空间在共享空间的角色、本人角色上限三者取最小）。成员空间通过 `access.readable_bases` 读取与检索共享来的库（原有的租户级 `resource_grants` 路径保留，供智能体绑定使用）；修改库、文档与共享仍只属于所属空间，因此 editor / admin 目前只记录和显示。接口：`/knowledge/bases/{kb_id}/shares`（列表、共享或改级别、`DELETE …/{shared_space_id}`）与 `/knowledge/shared-bases`（共享给我的库）。

**功能范围**：完整保留 WeKnora 知识库功能。后端能力目录逐项返回已实现（附是否经过真实环境验证）或待实现及所属阶段；前端不隐藏任何入口，待实现项标记并禁止提交，后端对选择待实现能力的写请求返回 `capability_planned`。

**存储**：关系数据库保存知识库、文档、不可变文档版本、作业、文本块定位与引用关系；原文件走可注册的存储后端（首批本地目录）。向量与关键词索引走可注册的向量库（`VectorIndex` 端口），每个知识库选择一个：首批实现 SQLite（本地开发，已测试）、PostgreSQL pgvector、Qdrant、Elasticsearch、Milvus（后四种待真实环境验收），其余引擎待实现。每个引擎必须把 Pre-Filter 的范围作为服务端过滤条件。图谱走可注册的图存储（`GraphStore` 端口）：内置（实体、关系、社区、社区报告存关系表，参考 RAGFlow）或 Neo4j（参考 WeKnora）。

**生命周期**：
1. 知识库、文档、版本、解析与索引任务、文本块、来源定位与引用契约。
2. 创建、更新、删除、上传、去重与版本。原文件保留在对象存储，数据库保存元数据与状态。
3. 解析与分块作为可恢复后台任务，记录阶段、重试次数、失败原因与幂等标识。首期支持文本、Markdown、PDF；扫描 PDF 的 OCR 另行确认。
4. 每个文本块关联文件、版本、页码或章节。重建索引使用新索引版本，不混用新旧块。

**检索**：
1. 同一批有版本与来源的文本块同时建立关键词索引与向量索引。
2. **先确定调用者有权访问的知识库与文档范围，再在范围内检索**（Pre-Filter）。不得先全局召回再过滤。
3. 合并关键词与向量候选，可选重排；保留召回通道、分数、来源与索引版本，结果可诊断。
4. 提供 `search_knowledge`、`read_document`、`list_documents`；答案引用回到文档版本与文本块。
5. 向量服务异常时返回可解释的降级结果；不得绕过权限，不得伪造引用。

**证据登记**：检索结果进入上下文时登记为 `[ID:n]`，同一 Run 内去重，挂起恢复后编号不变；模型输出的引用必须指向已登记句柄。无效引用不生成引用、在界面标为无效并记录 `knowledge.citation_invalid` 事件，Run 不因此失败；评估集把无效引用计为失败。检索只通过工具进行，不在每轮自动注入。

**图谱增强（可选，按知识库启用）**：
- 模式：`entity`（WeKnora 实体关系抽取）、`graphrag_light`（实体关系向量检索与 n 跳邻居）、`graphrag_general`（再加实体归并、社区划分与社区报告）；模式与图存储独立组合。
- 可单独开启图谱，配置实体类型、关系类型、抽取约束、归一规则与模型配置版本；schema 应窄而明确。
- 图元素记录知识库、文档版本、来源块、抽取时间与 schema 版本；原文块仍是证据事实源，图是可追溯的派生数据。
- 实体归一保守：不得仅凭名称相似合并不同公司、证券、人物或事件。
- 图谱写入按知识库与索引版本隔离，新版本构建完成后才切换可见。
- 图检索有界（种子实体、关系数、跳数、证据块、耗时、模型调用均有上限）；被截断时明确告知，不能把未返回的关系解释为"不存在"。
- 图服务超时或索引缺失时回退到基础检索并记录降级；权限拒绝不得回退为越权搜索。

**验收要点**：同一智能体可绑定多个知识库；无权的库与文档不通过向量或图谱路径泄漏；文档更新、删除、撤权与索引重建同步处理向量与图谱索引，旧版本不再被召回；基础检索不依赖图谱。

### 2.11 权限、授权与审批

借鉴：WeKnora `approval/`（gate、grants，会话级授权）、`types/agent_grant.go`（授权与配置哈希绑定）、`application/service/agent_share_scope.go`（共享智能体不扩大底层资源）；Hermes `tools/approval.py`（危险命令检测）；Octop `agents/security/`（`policy_store.py` 全局安全策略、`hitl_session.py` 会话内放行且不跳过追问、`tool_guard_rules.py` 工具守卫规则）。

**身份**：`Principal` 由认证适配器提供（`issuer + subject`）。首次访问映射为本地用户；禁用用户拒绝访问。开发模式使用固定单一主体，不信任请求头中的用户标识。

**空间与成员**：Tenant 是资源所属范围（参考 WeKnora Tenant）。`MembershipRecord` 保存角色；非成员返回 404，角色不足返回 403。

**组织与空间绑定**：组织是一棵树（集团为根，子公司与部门为节点，层级不限）。人员就是 `users`，可属于多个节点，其中只有一个主节点。平台管理员（`users.is_platform_admin`）管理树、人员与空间绑定。空间绑定到节点后，空间成员可以看到该节点的子树与去重后的人员；人员不会因此成为空间成员，加入须由空间管理员从绑定子树中显式选人（`members:manage`）。组织侧审计写入 `org_audit_records`，因为组织可以不绑定任何空间。

**资源归属**（提案 `2026-11-11-enterprise-saas` 决定 2）：智能体与知识库分为个人与企业两种归属，由创建入口决定（工作台创建个人资源，`/tenants/{id}/admin/...` 创建企业资源）。个人资源只由创建者维护；企业智能体只由持有 `enterprise_agents:manage` 的成员维护，企业知识库由持有 `enterprise_kbs:manage` 的成员管理，并可指定知识库管理员维护内容（`knowledge_base_maintainers`）。角色分配与共享只授予使用权（`view`、`run`）。空间 owner、admin 对个人资源只有治理权：查看、归档或删除、转为企业资源。企业智能体不能绑定个人知识库，个人智能体只能绑定创建者本人的个人知识库与企业知识库。

**企业即租户**（提案 `2026-11-11-enterprise-saas` 决定 1）：租户只有企业（`enterprise`）与保留的系统租户（`system`）两种；自助注册即创建一家企业，注册人为 owner，企业名称与编码不填时自动生成。一个账号可属于多家企业，登录默认进入上次使用的企业，否则进入最早加入的企业。

**部门与成员授权**（决定 5，`authz/audiences.py`）：智能体可分配给部门（可含下级）与成员，只授予使用权；知识库可设为 `scoped`，由部门与成员受众读取。按检查时的组织关系判断。他人可用的智能体只能绑定其使用者都能读取的知识库：`tenant` 库总可以；`scoped` 库要求智能体的使用者正好是被库受众覆盖的部门与成员受众（有角色授权或共享空间共享时不行）；收窄库会让已绑定的智能体失效时拒绝（`kb_in_use`）。

**用量与配额**（E6，`usage/service.py`）：Run 结束时把其 `model.completed` 事件中的用量按日加入 `usage_ledger`；企业、部门（含下级成员）、成员可设月度 Token 上限（输入加输出），提交 Run 时超限返回 429 `quota_exhausted`。

**数据治理**（E7，`governance/retention.py`）：设置了 `retention_days` 的企业，超期且没有进行中 Run 的会话由 worker 清除内容（消息、Run 事件、产物），会话保留为 `purged` 空壳；审计记录可按日期导出为带哈希链的 JSON Lines（`audit:read`）。

**企业策略**（`enterprise_policies`，`tenants/policies.py`，决定 4）：只收紧平台已有的检查，缺省行即默认值。`self_build_agents`（`all` / `org_units` / `none`，owner、admin 不受限，viewer 不能自建）决定谁能创建个人智能体；`personal_models`（默认关闭）决定成员能否使用个人模型与 Key，关闭后下一次选择或执行即被拒绝；`external_sharing`（默认关闭）决定能否共享到含其他企业的共享空间；`personal_wecom_channels`、`personal_external_channels` 供 IM 渠道使用；`retention_days` 供数据治理使用。读取接口 `GET /tenants/{id}/admin/policy` 对全体成员开放，修改 `PATCH` 需要 `policy:manage`。

**部门批量角色分配**：成员管理与角色管理权限同时满足，且目标角色 menus/apis 为操作者有效授权的子集时，才可给启用部门的直接活跃非 owner 成员批量分配；与单成员分配共用授予范围校验。操作在企业锁与同一事务中完成，已有分配跳过，不含下级与未来成员；页面额外通过组织管理权限读取完整部门路径。

**内置角色**（决定 8）：每家企业创建时写入 `security_admin`（`policy:manage`、`tools:manage`、`audit:read`）与 `auditor`（`audit:read`），`tenant_roles.builtin` 为真，可以分配，不能改授权。`policy:manage`、`audit:read_content` 属于治理权限，admin 默认不持有。

**知识库可见范围**（决定 3）：`knowledge_bases.visibility` 为 `private` 或 `tenant`。新建个人库默认 `private`（只有创建者与 owner、admin 可读），新建企业库默认 `tenant`；企业库设为 `private` 时只有管理者、知识库管理员与 owner、admin 可读。他人可用的智能体（企业智能体、有角色授权或共享空间共享的个人智能体）只能绑定 `tenant` 库，发布、分配与共享时检查；被这类智能体绑定或已共享到共享空间的库不能改为 `private`（`kb_in_use`）；只有 `tenant` 库能共享到共享空间。

**三类授权严格分离**：

| 类型 | 含义 | 范围 |
|---|---|---|
| ResourceGrant | 空间之间显式共享资源 | 资源层 |
| ActionGrant | 用户对某类动作的可记忆授权，绑定 session 或 automation 作用域、配置哈希、风险等级、过期与撤销 | 动作层（表 `action_grants`） |
| ActionApproval | 单次审批决定 | 单个调用 |

Tenant 角色与资源共享不能替代 ActionGrant 或审批。共享智能体不扩大其底层资源的权限。

**执行时复核**：每次工具调用、检索和资源读取都重新查询成员、资源状态、绑定与授权。撤权在下一次调用时生效。

**审批流程**：高风险调用生成 `approval.requested`，进入 `waiting_approval`；决定后经 `approval.resolved` 继续或拒绝；决定与依据写入审计。

**会话放行**（提案 `2026-11-06-tool-call-hardening`，已实施）：审批时可选「本会话允许」，在 `action_grants` 写入 `scope='session'` 的 ActionGrant，绑定会话、智能体版本和工具名。`destructive` 工具和参数守卫触发的审批不能放行；放行在每次调用时查询，撤销立即生效。接口 `GET/DELETE /api/v1/tenants/{tenant_id}/native/sessions/{session_id}/tool-grants`，只允许会话所有者访问；对话页顶栏列出已放行的工具并可撤销。

**危险命令检测**：作为审批触发条件，不作为唯一防线；检测结果与授权共同决定。

**审计**：工具调用、授权判断、审批、模型请求与资源访问都写入审计，包括主体、空间、Run、结果状态与时间。秘密不进入审计与事件。

### 2.12 会话、事件与持久化

**数据表**：

| 表 | 用途 |
|---|---|
| `users`、`tenants`、`tenant_memberships` | 身份、空间与成员角色 |
| `agents`、`agent_draft_bindings`、`agent_versions`、`agent_resource_bindings` | 智能体、草稿绑定、不可变版本、资源绑定 |
| `platform_resources`、`resource_grants` | 资源登记与空间间显式共享 |
| `sessions`、`messages`、`session_checkpoints` | 会话、消息（assistant/tool 消息带内部 Runtime 元数据）、工作检查点。历史 Run 只回放 user 与最终 assistant 行，tool 行仅属于其所在 Run |
| `runtime_session_bindings` | 平台会话与外部 Runtime 会话 ID 的映射 |
| `runs`、`run_events`、`outbox_records` | 运行、事件（sequence 游标）、Outbox 队列（多租户派发载体） |

**Watchdog 事件**：`run.watchdog_alert`（payload：`rule`、`observed`、`threshold`）与 `run.watchdog_ack`（用户选择继续等待）。`tool.started` 的 payload 含 `signature`（工具名加参数摘要，不含原始参数）。Run 响应的 `attention_required` 由事件派生：最新的告警晚于所有非 Watchdog 事件与确认事件时为 true，因此不需要额外列或迁移。确认接口为 `POST /tenants/{tenant_id}/runs/{run_id}/watchdog/acknowledge`（202，返回 Run 视图），终态 Run 上不写入确认。
| `runtime_epoch`、`session_admissions` | 派发账本：进程代际、会话入队记录（queued、started、unknown、terminal） |
| `session_snapshots`（或会话表快照列） | 版本化的会话状态快照（JSON，v2）与水位 |
| `native_run_states`、`run_directives` | Native 预算累计与运行指令 |
| `run_input_requests`、`action_approvals` | 等待输入的问题与回答；单次审批 |
| `tool_invocations` | 工具调用记录（幂等键、副作用标记、结果状态） |
| `tool_outputs` | 超过 `tool_output_inline_limit` 的工具输出原文，按 Run 隔离；模型只见预览与句柄，经 `read_tool_output` 分页读取，每次读取写审计 |
| `memory_drafts`、`memory_entries`、`memory_versions`、`memory_tombstones`、`memory_fts`（仅 SQLite）、`context_summaries` | 记忆草稿、已发布条目与版本、被拒绝内容的墓碑、SQLite 关键词索引（派生，可由当前版本重建）；上下文摘要为追加式（每行 `supersedes_id` 指向被替代的行，只有切点前移才写入，原行不改写） |
| `model_profiles`、`model_profile_versions`、`model_providers`、`provider_models`、`model_defaults`、`native_preferences` | 模型配置版本、供应商、默认与偏好 |
| `provider_credentials`、`credential_references` | 加密凭据与凭据引用 |
| `audit_records` | 审计记录 |
| `action_grants`、`run_snapshots` | ActionGrant；等待审批时的版本化运行快照 |

**派发账本**：所有部署共用同一套规则，只有存储后端不同。
- `runtime_epoch`：每次进程启动递增，所有账本写入带当前 `owner_epoch`；过期 epoch 的写入返回 `stale_epoch`。
- `session_admissions`：状态为 `queued`、`started`、`unknown`、`terminal`。领取用条件更新 `UPDATE ... SET status='started', owner_epoch=:e WHERE id=:id AND status='queued'`，rowcount 必须为 1；按 `seq` 取队首。会话存在 `started` 或 `unknown` 记录时不领取。
- 启动恢复：`owner_epoch` 小于当前值的 `started` 与执行记录转为 `unknown`，会话阻塞，不自动重放。解除入口：`POST /tenants/{id}/runs/{run}/resolve-unknown`（Run 所有者与租户 owner / admin，幂等）、`GET /tenants/{id}/admissions/unknown`、命令行 `list-unknown` / `resolve-unknown`，均记审计；定时任务会话在启动恢复时自动解除，`[platform].auto_resolve_safe_unknown`（默认关闭）开启后无未完成副作用调用的 Run 也自动解除；会话消息接口返回 `blocked`，前端提示并提供解除按钮。
- 忙时排队：会话已有执行中的 Run 时，新提交的 Run 以 `queued` 入队，接口返回 202，`run.queued` 事件与响应带 `queue_position`（1 表示下一个执行）。每会话排队上限 32，超限返回 409 `session_queue_full`，不写入任何记录。
- 派发：worker 在 Run 开始前检查 FIFO 队首。不是队首、会话被 unknown 阻塞、或领取冲突时，释放 Outbox 租约并延后 2 秒再次投递，Run 保持 `queued`，不写失败事件。
- 默认不打断。打断与转向不是提交的默认行为；用户显式取消通过取消接口完成。取消排队中的 Run 时，其 FIFO 位置由终态写入释放，后续条目前移。全局活跃会话上限 `max_concurrent_sessions`（`configs/nexus.toml [platform]`，缺省 8）：提交一个新会话时，若已有该数量的会话持有 queued、started 或 unknown 记录，返回 503 `session_capacity_exceeded`，不写入任何记录。同一会话的后续 Run 不占新名额。多进程 PostgreSQL 下计数与插入不在同一锁内，上限可能被短暂超出，需以数据库锁或计数器补齐（随 2.9）。

**多租户队列**：PostgreSQL Outbox 表作为派发载体。Run 与 Outbox 记录在同一事务提交；worker 使用 `SELECT ... FOR UPDATE SKIP LOCKED` 领取，写入带过期时间的租约。队列语义为至少一次，由账本的 CAS 领取与幂等约束阻止重复执行。租约丢失或进程崩溃后，未完成的执行转为 `unknown`，不自动重放副作用。

备选方案：Redis Streams 与数据库不在同一事务，需要持续对账；RabbitMQ 增加运维成本。当前规模不需要。复评条件：队列积压、数据库连接争用、Outbox 维护成本，或需要多类型消息路由。

**事件**：持久序号 `sequence` 作为 SSE 的 `id` 与 `Last-Event-ID` 游标；JSON 响应保留独立 `event_id`。先提交事件再投递。每页最多 500 条；SSE 名称为 `run.event`。等待或终态结束当前连接；浏览器重连不创建新 Run。

**实时事件通道**（openspec `2026-11-07-run-event-streaming`）：数据库是 Run 与持久事件的唯一事实源；通道只携带一份实时副本，加上不入库的临时事件（`message.delta`）。通道丢失、断档或不可用只影响实时性，不影响最终状态。

| 后端 | 配置 | 说明 |
| --- | --- | --- |
| `database`（默认） | `[run_events].backend` | 无额外服务。每个 API 进程、每个活跃 Run 一个共享轮询器向所有订阅者扇出，间隔在 `poll_min_ms` 到 `poll_max_ms` 间自适应；`message.delta` 仍写库 |
| `redis` | 需 `uv sync --extra redis` | Redis Streams：`XADD MAXLEN ~`、阻塞 `XREAD`、断档返回 `StreamGap`、生产者令牌围栏（Lua 比较后写入）、取消唤醒；`message.delta` 不写库 |
| `memory` | 仅 `embedded` | 进程内有界日志，条件变量唤醒 |

- 事件分级：持久事件（除 `message.delta` 外）同事务写库，提交后由 `Session` 的 `after_commit` 钩子发布到通道（事件统一经 `SqlAlchemyRunEventRepository.append`，回滚则丢弃，通道不会出现库里没有的事件）；临时事件只发布到通道，不带 SSE `id`，`Last-Event-ID` 永远指向持久序号。每个回合结束时与助手消息同事务写入持久事件 `message.completed {turn, text}`，已完成 Run 的历史时间线只靠持久事件重建。
- 订阅顺序：先从数据库重放 `after_sequence` 之后的持久事件，再读通道；持久事件按 `sequence` 去重，序号跳跃则从数据库补读（也修复通道漏发）；已被 `message.completed` 覆盖的回合的临时文本丢弃；断档、结束标记、生产者租约过期各自补读数据库后再收尾。续连（游标大于 0）先发 `stream.resync`，客户端丢弃未入库文本后再收到通道回放。
- SSE 为异步生成器：连接内不持有数据库会话与线程，授权与重放使用短会话；空闲时按 `heartbeat_seconds` 发心跳注释。
- 控制与标记：取消请求同时写库并向 Run 的控制键发信号，worker 的监视循环阻塞等待该信号，数据库租约与取消检查降为每 `lease_check_seconds` 一次；信号丢失只退化为该间隔。会话的活动 Run 标记（`GET /sessions/{id}/live-run`）随执行续期、终态清除。
- 并发：一个 worker 进程在一个事件循环里以协程并发执行最多 `[worker].max_concurrent_runs` 个 Run（默认 32；同一会话仍先进先出一次一个，实际并发还受 `max_concurrent_sessions` 限制），同步数据库调用走专用线程池（`db_threads`，引擎连接池为其加 4），模型连接池由所有 Run 共享；SQLite 单写者，有效并发固定为 4，文件库引擎使用 WAL、忙等待超时与 `BEGIN IMMEDIATE` 使并发写入排队而不是报错。`embedded` 是 API 进程内的一个 worker 线程，线程里同样是一个事件循环，使用独立的数据库引擎。要用多核就多开 worker 进程。准入在全局活动会话上限之外支持 `max_concurrent_sessions_per_tenant` / `_per_user`（默认不限，超限 429 `session_limit_reached`），后台模型调用可按模型限流（`[model_limits]`，不影响交互式 Run）。

**输入回答**：`POST .../runs/{run_id}/input` 携带 `input_request_id`、回答与 `Idempotency-Key`；重复提交返回相同结果；回答继续同一 Run，预算累计。

**运行约束**：
- 运行提交与输入回答要求 `Idempotency-Key`；同一键重复提交返回原结果。
- 长任务不在 HTTP 请求中执行；提交即返回 Run，状态通过事件与游标读取。
- 启动、迁移与配置错误必须以可读信息失败，不输出凭据。

**数据库**：
- 多租户：PostgreSQL 为事实源，SQLAlchemy 2.x 与 psycopg 3。
- 单机：SQLite 单文件为事实源，两个进程共用；写入使用 `BEGIN IMMEDIATE`，WAL 模式。它是本方案的应用后端，不再只用于测试。
- 两种后端通过同一组端口（账本、快照、事件）接入，业务代码不区分后端。
- Alembic 迁移由发布或运维命令显式执行，不在 API 或 worker 启动时自动运行。API 与 worker 使用同步 Session；core 不暴露 ORM 类型。

**会话缓存**：历史消息行的缓存 key 为 `(session_id, watermark)`。水位在每次快照保存与每条消息写入时递增，同一 key 的内容不变，因此不需要失效，多个进程共用也不需要协调。缓存只保存未经授权过滤的原始消息行；每次运行都重新检查来源 Run 的资源授权，撤销即时生效。缓存不含权限结果、凭据明文和超阈值工具输出原文。工具调用的权限在每次调用时查库。容量用 LRU、空闲 TTL 与单条目字节上限约束（256 entries / 900 s / 256 KiB，为估计值）。进程重启后缓存为空。

**乐观并发**：保存快照带预期水位，不一致则以 `session_watermark_conflict` 拒绝并重新读取。消息写入只递增水位，不做比较。

**连接配置**：`configs/nexus.toml` 的 `[database].url` 为唯一来源，显式参数优先。API、worker 与 Alembic 共用解析逻辑；环境变量与 `.env` 不参与配置。

### 2.13 模型与凭据

借鉴：自研为主；Octop `agents/providers/`（`presets.py` 供应商预设、`probe.py` 连通探测、`health.py` 健康与故障转移分类）、`crypto/sealed_repos.py`（秘密字段落库加密）；octop-harness `llm/factory.py`（由供应商与模型配置构建客户端）、`llm/http_timeout.py`（统一超时策略）、`usage.py`（跨供应商的用量归一）。

- **配置**：供应商记录归属 Tenant；`owner_user_id` 非空时仅该用户可用，为空时为空间共享。每个供应商有多个 ModelProfile，修改产生不可变版本。
- **协议**：`options.protocol` 必须显式设置（如 `openai_chat_completions`），不从供应商名称猜测。首个适配器使用锁定版本的 `openai` SDK 异步 Chat Completions 流；禁用 SDK 自动重试；工具执行后不重放整个回合。
- **凭据**：Key 通过 API 一次性接收，使用 Fernet 加密保存在独立凭据表。主密钥经环境注入 API 与 worker，不写入数据库或仓库。缺少主密钥或密文无效时拒绝解析，不回退为明文。
- **部署模型凭据**：`env://NAME` 引用需同时登记在 `configs/nexus.toml` 的 `[model_credentials]` 中，未登记的名称一律拒绝。
- **网络出口**：HTTPX 调用经目的地址策略：默认只允许公网 HTTPS，检查 DNS 解析结果并固定 IP，保留 TLS/SNI 校验，禁用重定向，不使用环境代理。连接测试与正式调用共用同一策略。
- **默认与固定**：显式模型优先于个人默认，个人默认优先于空间默认。默认只用于新智能体选择，不改已发布版本与已有会话。个人模型在发布、会话创建和执行时都校验归属。
- **运维边界**：主密钥丢失则密文无法恢复，需纳入部署秘密管理备份；轮换需离线重加密，不提供自动轮换。停用供应商不撤回已发出的请求，之后的回合拒绝执行。
- **错误分类**：`model_authentication_failed`、`model_request_rejected`、`model_quota_exhausted`、`model_response_failed`、`timeout`、`rate_limited`、`provider_unavailable`、`context`、`stream`、`model_credential_unavailable`。供应商正文与认证信息不进入错误文本。
- **用量**：保留 input、output、cache_read、cache_creation 字段；total 按协议归一；缺失时估算。

### 2.14 渠道（connectors）

借鉴：LobeHub 渠道适配器的组织方式（`chat-adapter-*`）；Octop `infra/gateway/`（多 IM 通道归一为同一处理链路，渠道内审批 `gateway/hitl/`）；octop-gateway（`channel.py` 渠道抽象、`manager.py` 按会话合批、`constraints.py` 平台限制与限流、`push_routing.py` 主动推送路由、`channels/wecom.py`、`channels/feishu.py`、`channels/dingtalk.py`、`channels/telegram/delivery.py` 只在明确拒绝时重试、`channels/telegram/policy.py` 先准入再取媒体）。

- **每个渠道绑定一个智能体**（提案 `2026-11-11-enterprise-saas` 决定 6，`agent_channels`）。种类：`wecom_app`（智能体用途的企微自建应用消息，经企业的企微回调进入）、`wechat`（创建者本人的微信，腾讯 iLink 扫码绑定、长轮询收消息，只服务绑定者）、`wecom_bot`、`qq`（平台条件未核对，创建时返回 `channel_kind_unverified`）。企业智能体的渠道由 `enterprise_agents:manage` 添加并立即生效；个人智能体的企微机器人按企业策略 `personal_wecom_channels` 审核、开放或禁止，微信与 QQ 由 `personal_external_channels` 控制；策略收紧时已启用的渠道随之停用。
- **入站**（`channels/service.process_inbound`）：按平台消息 id 去重（`channel_messages`）→ 企微渠道按 `(wecom, corp_id, userid)` 找到成员，微信与 QQ 只接受绑定者 → 检查渠道状态、企业策略、成员身份与智能体使用权（不满足时立即回复“无权限”或“未开通”）→ 以该成员身份在其（渠道、会话、成员）专属会话（`channel_session_bindings`）中提交 Run，并记下待发回复（`channel_deliveries`）。
- **回复**：worker 的空闲任务在 Run 停下（完成、失败、取消，或需要到工作台确认）后发送回复，超过 1800 字截断并附工作台链接；只有网络类错误重试，最多 3 次。
- **长连接**：worker 按租约（`lease_owner`、`lease_until`，90 秒）领取渠道，同一渠道同一时刻只有一个持有者；令牌失效的微信渠道转为 `expired`，由创建者重新扫码。
- **企业微信自建应用**（E3，`wecom/`）：每家企业绑定一个企微企业（`tenant_wecom_corps`），登记多个自建应用（`tenant_wecom_apps`，用途 `workspace` / `admin` / `agent`）。应用主页 `/wecom/apps/{id}/entry` 在企微内免登，扫码登录经 `/api/v1/auth/wecom/qr?enterprise_code=`；已同步的成员首次进入自动开户（`contributor`）。通讯录由扫码登录应用的密钥读取（只含其可见范围），每天同步一次，或在请求或回调后尽快同步；部门写入 `org_units`（`source = wecom`），成员写入 `wecom_members`；被删除或移出范围的成员撤销企业成员身份（owner 除外），资产不动。回调 `/api/v1/integrations/wecom/{tenant}/callback` 先验签解密再处理。

### 2.15 Web 工作台

借鉴：WeKnora 固定版本 `e1f9a6166` 的 Vue 前端，按 Nexus 身份、企业与 Runtime 契约适配。

- **技术**：Vue 3 + TypeScript + TDesign、Pinia、vue-router、vue-i18n，Node.js 22.12+，pnpm 10。
- **工程**：`apps/web` 是 pnpm workspace，包含公共源码包 `core`、员工工作台 `workspace` 与企业管理后台 `admin`。API、认证、语言和主题基础逻辑已抽取；管理后台已有独立登录、企业切换、服务端权限导航、企业信息、角色与权限（含企业智能体使用授权）、审计日志、企业策略、成员邀请、加入申请审批和部门组织页面，其他业务页面及共用编辑器仍按 E2 迁移。两个应用独立构建，管理应用 base 为 `/admin/`；公共包不依赖应用，应用互不依赖。当前尚未完成工作台移除管理代码的产物门禁。
- **认证与旧入口**：两个应用共用登录、改密和未知页面提示。工作台只恢复已有令牌，不调用桌面自动初始化；自助注册只创建企业，邀请注册加入既有企业。平台管理页面与路由已删除，企业管理业务页面仍按 E2 迁移。
- **设置与管理界面**：企业管理主框架对齐 workspace 的品牌、可折叠图标侧栏和左下角账户入口，支持企业切换与退出，不提供返回工作台入口；内容页复用 `core` 的主题、TDesign 覆盖和设置行/表格样式，`SettingsModalShell` 继续服务工作台设置与编辑器。
- **界面约定**：浅色、扁平卡片、青绿色主色、系统字体，适配桌面与窄屏；键盘焦点可见、对比度达标、加载与错误有反馈、减少动态效果。规划中的功能显示为"待接入"，不显示虚构的运行数据。
- **信息结构**：智能体管理、会话工作台、技能/工具/MCP 资源、知识库、渠道、设置、观澜工作台。类型标签展示能力来源；资源绑定同时显示兼容状态与版本。
- **安全**：模型输出按纯文本渲染，不作为 HTML 执行。
- **API**：业务接口位于 `/api/v1/tenants/{tenant_id}/...`；观澜接口位于 `/api/v1/guanlan/...`。`/agents`、`/skills`、`/knowledge-bases`、`/channels`、`/artifacts` 等为规划接口。

### 2.16 观澜（股票研究，领域扩展）

借鉴：TradingAgents（分析员报告 → 多空辩论 → 研究经理综合；决策回填）；daily_stock_analysis（专业分工、分析深度分级、中间观点结构化，未深读）；Qlib（训练与推理分离，未深读）。取舍：作为领域包，通过公共协议注册工具和技能。

**数据边界**：结构化行情与财务（观澜数据服务）、研报与公告（知识库证据）、分析规则（专家审核的版本化规则）三者分开，互不替代。

**数据源**：通过 `guanlan/data` 适配器接入，智能体与技能只调用项目工具。候选数据源须逐接口验证覆盖市场、历史范围、更新频率、稳定性、使用条款与商业限制；不把"库中存在接口"当作 SLA 或授权保证。

**时点与来源**：每条数据保留 provider、获取时间、数据对应时间、复权与口径；无法确认的字段明确标记，不推断补齐。采集由 worker 定时调度。

**研究流程（候选步骤；步骤 4、5、7、8 是否必选待确认）**：

| 步骤 | 目的 | 产物 |
|---|---|---|
| 1. 明确任务 | 标的、市场、问题、预测周期、数据截止时点 | 任务范围与 as-of 时点 |
| 2. 准备证据 | 获取行情与财务，检索公告与研报 | 带来源、版本与时点的证据集 |
| 3. 分项分析 | 技术、基本面、事件分别整理，区分事实、推断与缺失 | 分析员报告 |
| 4. 量化参考（可选） | 对明确目标与周期调用已发布模型 | 预测结果、验证摘要、限制 |
| 5. 多空论证（可选） | 多头与空头围绕共同证据互相回应 | 带引用的辩论记录 |
| 6. 综合结论 | 权衡论据质量、证据强弱、模型适用性与不确定性 | 结构化结论与理由 |
| 7. 风险复核与报告 | 检查风险、情景与结论边界 | 含时点、引用、风险与限制的报告 |
| 8. 评估与回测（适用时） | 评估研究质量或策略表现，防未来泄漏 | 可复现评估记录 |

辩论依赖提示词，不是规则引擎，也不是投票。

**模型工具**：作为量化证据来源，结果携带预测目标、周期、数据时点、模型与特征版本、验证摘要和适用限制。技能只描述何时调用，不授予权限。

**研报与规则治理**：研报保留来源、作者、日期、适用市场与行业、版本；检索结合标的与时间范围，并呈现相互矛盾的观点。可复用方法经专家审核后提炼为规则，并可追溯到原始研报。硬约束由程序校验，需要权衡的部分交给智能体，并要求给出依据与不确定性。

**回测**：历史回测不能由智能体文字结论替代，须处理复权、交易成本、停复牌、退市与未来信息泄漏；基准、成本与时间段必须记录。

**范围说明**：本节描述目标设计，不表示对应能力已经实现。
