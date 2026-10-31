# Hyoga Nexus 总体架构

状态：2026-10-31 重构。本文件描述目标架构、模块与参考项目的对应关系、目录边界与关键决策。实施顺序与验收见 [roadmap.md](roadmap.md)。当前代码已实现的范围见第 10 节，未列入的能力不得宣称可用。

---

## 1. 架构原则

- **平台与运行时分离**：平台掌握身份、空间、授权、审批、事件与审计；Native、Codex、Claude Code 只是执行器，共用同一套契约。
- **授权在执行时复核**：每次工具调用、检索和资源读取都重新查询数据库，不信任快照、模型参数或技能声明。
- **事件先持久化再推送**：所有 Runtime 输出统一为 `RunEvent`；只有明确的 `completed` 才是成功。
- **参考项目借鉴设计，按职责拆分实现**：每个模块标明借鉴的参考项目与模块（第 2 节）；不嵌入整个第三方项目，不保留参考项目的超大单文件结构。
- **不确定即显式失败**：未知结果标记 `interrupted`，不自动重放有副作用的工具；未验证的能力标记 `unverified`，不对外宣称可用。

---

## 2. 模块总览与参考来源

```mermaid
flowchart TD
    W[Web 工作台 / IM 渠道] --> API[API 应用服务]
    API --> PLAT[platform: 身份 / 空间 / 授权 / 智能体版本 / 会话 / 运行 / 审批 / 审计]
    PLAT --> ROUTER[Runtime Router]
    ROUTER --> N[Native Engine]
    ROUTER --> C[Codex Adapter]
    ROUTER --> A[Claude Code Adapter]
    N --> GW[ToolGateway 授权工具网关]
    C --> MCP[平台 MCP 服务: 仅已授权工具]
    A --> MCP
    C -. 原生 shell/文件 .-> SB[受控工作区 / 沙箱]
    A -. 原生 shell/文件 .-> SB
    GW --> TOOLS[工具 / 技能 / 知识库 / 记忆 / 观澜工具]
    GW --> SB
    N & C & A --> EV[统一 RunEvent]
    EV --> DB[(PostgreSQL: 事件 / 调用 / 审批 / 审计)]
    EV --> SSE[SSE 续读]
```

| 模块 | 职责 | 借鉴的参考项目与模块 | 本项目的取舍 |
|---|---|---|---|
| `core` 运行时契约 | Runtime 端口、RunEvent、能力声明、错误码 | DeepSeek Harness `packages/core/agent-loop`（事件溯源、能力接缝） | 自研契约；不依赖厂商 SDK |
| `platform` 身份/空间/会话/运行 | 组织与生命周期 | WeKnora 的 Tenant、Session busy 控制、`suspend.go` 版本化快照 | Tenant 映射为 Workspace；用 PostgreSQL Outbox 替代 Redis 队列 |
| `platform` 授权与审批 | ResourceGrant、ActionGrant、ActionApproval、审计 | WeKnora `internal/agent/approval/`（gate、grants）、`types/agent_grant.go`；Hermes `tools/approval.py` | 三类授权严格分离；审批结果持久化 |
| Native 引擎 | 单 Run 的回合循环、完成判断、挂起恢复 | GenericAgent `agent_loop.py`（生成器循环、StepOutcome、坏调用恢复）；WeKnora `engine.go`（loopGuards）；OpenClaw `run-loop.ts`（外层恢复与预算伸缩）；Dify `fc_agent_runner.py`（最后一轮禁用工具）；n8n `executeBatch`（动作与执行分离） | 拆为 RunOrchestrator、TurnExecutor、CompletionJudge、ToolDispatcher，不保留单文件循环 |
| 上下文与压缩 | 前缀冻结、历史视图、压缩、证据句柄 | Hermes `memory_tool`（冻结快照）；WeKnora `compaction/`（cutpoint、overflow）；LobeHub `packages/context-engine`（可组合处理器）；RAGFlow `evidence_registry.go` | 处理器管线化，每个处理器可单独测试 |
| 工具与授权网关 | 工具定义、授权复核、结果投影、Spill | GenericAgent `ga.py`（`do_*` 分发、输出限制）；DeepSeek Harness `spill`（大输出落盘）；WeKnora `tools/`（工具策略） | 网关只能收紧权限；模型不能选择主体 |
| Codex 适配器 | 外部 Codex 执行与事件映射 | Hermes `agent/transports/codex_app_server.py`（JSON-RPC、initialize、版本门槛）；官方 `openai-codex` SDK | 事件与审批经 app-server 协议；SDK 管进程 |
| Claude Code 适配器 | 外部 Claude Code 执行 | 官方 `claude-agent-sdk`（无开源参考实现） | 实施前必须核对官方文档并锁定版本 |
| 技能 | 版本化指令包、依赖校验、来源检疫 | Hermes `tools/skills_guard.py`、`skills_hub`；DeerFlow `skills/`（projection、security_scanner、mutations） | 技能不授予权限；发布需审核 |
| MCP | 外部工具接入与平台工具暴露 | WeKnora `approval/mcp_risk.go`（高风险 MCP 审批） | 按工具启用；短时运行令牌 |
| 记忆 | 工作检查点、用户事实、SOP、归档 | GenericAgent `memory/` 四层结构与 SOP；Hermes `memory_tool.py`；DeerFlow `agents/memory/`（后端契约、prescreen）；TradingAgents `memory/log.py`（决策回填） | 所有写入为草稿，审核后才进入提示 |
| 沙箱 | 命令与文件执行接缝、租约、虚拟路径 | DeerFlow `sandbox/`（lease、虚拟路径、原子写）；Hermes `tools/environments/`；FastGPT `projects/agent-sandbox` | 无验收后端前不注册执行类工具 |
| 知识库 | 文档生命周期、混合检索、引用、可选图谱 | RAGFlow `internal/agentic_rag/`（证据登记、判断与断路、检索工具正交化）；WeKnora（Pre-Filter、图谱权限） | 用 Python 重写，不依赖 RAGFlow 或 WeKnora 服务 |
| 模型与凭据 | 供应商、模型配置版本、加密 Key、网络出口 | 自研，无对应参考模块 | Fernet 加密；HTTPX 目的地址策略 |
| 渠道 | 企业微信、微信、QQ 消息接入 | LobeHub `chat-adapter-*` 的组织方式 | 只做消息标准化与投递，不复制智能体循环 |
| Web 工作台 | 智能体、会话、资源、知识库、设置界面 | 自研 | 界面约定见第 5.15 节 |
| 观澜（领域） | 股票数据、研究流程、模型工具、回测 | TradingAgents `graph/setup.py`（分析员→多空→研究经理）、`memory/reflection.py`；daily_stock_analysis（分工与分析深度分级，未深读）；Qlib（训练与推理分离，未深读） | 作为领域包，通过公共协议注册工具和技能 |

参考项目的固定版本与许可证见第 8 节。

---

## 3. 依赖规则

| 包 | 职责 | 边界 |
|---|---|---|
| `core` | 标识、端口、DTO、事件、错误码、运行时契约 | 不依赖其他本地包或厂商 SDK |
| `platform` | 身份、空间、智能体版本、资源绑定、会话、运行、队列、凭据引用、授权、审计 | 编排公共服务；不导入 `guanlan` |
| `runtimes` | Native 引擎与外部适配器 | 厂商 SDK 类型不出适配器边界 |
| `tools` | 工具定义、注册、授权网关、通用内置工具 | 领域工具属于领域包 |
| `skills` | 技能发现、解析、版本、依赖、来源检疫 | 技能只描述流程，不授予权限 |
| `mcp` | MCP 客户端、服务端、按工具暴露 | 不默认开放整个服务 |
| `memory` | 记忆契约、草稿、审核、检索注入（目标包，见第 4 节） | 不依赖 Runtime；写入带来源与作用域 |
| `knowledge` | 文档、解析、分块、索引、检索、引用 | 全 Python；不与记忆或结构化行情数据混用 |
| `sandbox` | 执行后端接缝、工作区、租约、产物 | `local` 只用于显式开发模式 |
| `connectors` | 渠道消息标准化与投递 | 不复制智能体循环 |
| `guanlan` | 股票数据、研究、回测、领域工具 | 通过公共协议注册工具和技能 |

`apps/` 是组合根：`api` 装配 HTTP，`worker` 装配后台任务与 Runtime，`web` 提供交互。领域扩展由入口显式注册。

---

## 4. 目录结构

### 4.1 当前结构

```text
hyoga-nexus/
├── apps/
│   ├── api/src/nexus_api/           # FastAPI 入口、http、schemas、dependencies
│   ├── worker/src/nexus_worker/     # 后台入口、jobs、Native 装配
│   └── web/src/                     # Vue 3 + Element Plus 工作台
├── packages/
│   ├── core/src/nexus_core/         # 公共协议、runtime、events、tools、tasks
│   ├── platform/src/nexus_platform/ # identity、workspaces、agents、sessions、runs、
│   │                                # resources、models、memory、jobs、persistence、observability
│   ├── runtimes/src/nexus_runtimes/ # native（context、engine、hooks、models、prompts）、adapters
│   ├── tools/src/nexus_tools/       # registry、gateway、builtins
│   ├── skills/src/nexus_skills/
│   ├── mcp/src/nexus_mcp/
│   ├── knowledge/src/nexus_knowledge/
│   ├── sandbox/src/nexus_sandbox/
│   ├── connectors/src/nexus_connectors/
│   └── guanlan/src/guanlan/
├── skills/                          # 技能指令与资源内容（不是实现代码）
├── configs/                         # 非敏感示例；nexus.toml 为本地忽略文件
├── migrations/                      # platform、knowledge、guanlan 的 Alembic
├── tests/                           # 软件测试
├── evals/                           # 智能体、检索、技能、观澜评估样例
└── docs/                            # architecture.md 与 roadmap.md
```

### 4.2 目标调整（待确认，未实施）

下列调整依据第 2 节的参考项目，属于跨包重构，按仓库规范实施前需用户确认。当前代码未改动。

| 调整 | 理由 | 参考 |
|---|---|---|
| `platform/memory` 拆为独立包 `packages/memory` | Runtime 与知识库都需要记忆；后端契约应与平台解耦，便于替换存储 | DeerFlow `agents/memory/`（MemoryManager 契约）、Hermes `memory_tool` |
| `platform/resources` 中的授权与审计拆为 `platform/authz` | 授权、审批、审计是独立的变更原因，应与资源登记分开 | WeKnora `approval/`、`agent_grant.go` |
| `runtimes/native/context` 改为处理器管线 `context/processors/` | 冻结前缀、历史视图、压缩、证据登记各自独立 | LobeHub `context-engine`；WeKnora `compaction/` |
| `knowledge` 拆为 `ingest/`、`index/`、`retrieval/`、`evidence/`、`graph/`（可选） | 解析、索引、检索、图谱的失败模式和依赖不同 | RAGFlow 工具与判断拆分；WeKnora 图谱隔离 |
| `sandbox` 后端放入 `backends/`（`local`、`docker`、`ssh`） | 后端可替换，验收门禁按后端划分 | Hermes `tools/environments/`；DeerFlow `sandbox/` |
| `skills` 增加 `guard/`（来源检疫）、`projection/`（沙箱投射）、`review/`（审核发布） | 三类职责分别对应 Hermes 与 DeerFlow 的不同机制 | Hermes `skills_guard.py`；DeerFlow `projection`、`mutations` |
| 删除 `runtimes/adapters/deepseek` 占位 | 本方案不计划接入 | — |

### 4.3 拆分理由

- `core` 是稳定协议；`platform` 是应用服务；`runtimes` 是执行器，三者不混入同一个 Agent 类。
- 技能机制（`packages/skills`）与技能内容（顶层 `skills/`）职责不同。
- `packages/` 是可安装包，内部目录是模块，不等于独立服务。

### 4.4 当前实现与目标的差异

- 占位目录：`adapters/codex`、`adapters/claude_code`、`sandbox/docker`、`knowledge` 的解析与索引、`mcp` 的客户端与服务端、`guanlan` 的数据与分析。
- 第 4.2 节的目标调整均未实施。

---

## 5. 模块设计

### 5.1 运行时契约（core）

借鉴：DeepSeek Harness（事件溯源、能力接缝）；Hermes（执行后端接缝）。

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
- 有副作用的工具结果未知时标记 `interrupted`，不自动重放。

**终态映射**：

| 统一状态 | Codex app-server | Claude Agent SDK | Native |
|---|---|---|---|
| completed | `turn/completed`，`status=completed` | 结果消息且无错误（待核对） | `StepOutcome` 完成 |
| interrupted | `turn/completed`，`status=interrupted` | 取消确认（待核对） | 取消已生效 |
| failed | `turn/completed`，`status=failed` | 错误结果（待核对） | 异常或预算耗尽 |
| 工具 declined | commandExecution/fileChange 最终 `declined` | 权限拒绝（待核对） | 网关拒绝 |

### 5.2 Native 引擎

借鉴：GenericAgent `agent_loop.py`（循环形态、StepOutcome、坏调用恢复）；WeKnora `engine.go`（完成判断、守卫）与 `suspend.go`（挂起恢复）；OpenClaw `run-loop.ts`（外层恢复与预算伸缩）；Dify `fc_agent_runner.py`（最后一轮禁用工具）；n8n `executeBatch`（动作产出与执行分离）。

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
- **上下文**：系统提示与工具 schema 在 Run 开始时计算一次，Run 内不变，保护供应商提示缓存（参考 Hermes）。历史是事件流，模型可见消息由事件派生（参考 DeepSeek Harness）；压缩结果作为新事件写入，源事件保留。
- **压缩**：优先完整保留最近的消息与工具交换；较早内容压缩为标注过的局部摘录；仍装不下则显式失败 `model_context_exceeded`。
- **工具顺序**：同一回合内按模型声明顺序执行，每个调用独立记录 invocation；有副作用的工具之间不并发。
- **取消与等待**：取消信号在模型流、工具和沙箱调用的每个等待点检查；`ask_user` 类工具产生 `wait_input`，释放 worker，回答后在同一 Run 中幂等继续。
- **恢复**：恢复前校验快照版本、会话/空间/主体、Agent/模型版本、资源授权、审批消费状态与已完成的 invocation，再从挂起点继续。不依赖进程内锁、回调、SDK 句柄或临时资源。
- **钩子**：agent/turn/model/tool 的 before/after 类型化钩子，只接收稳定元数据 DTO，不暴露 locals、SDK 对象或凭据；异常隔离，超时忽略。
- **Run 状态**：queued、running、waiting_input、waiting_approval、completed、failed、cancelled、interrupted。同一 Session 仅允许一个活跃 Run（含等待态），由服务检查与数据库部分唯一索引共同保证。

### 5.3 Codex 适配器

借鉴：Hermes `codex_app_server.py`（JSON-RPC over stdio、initialize 握手、版本门槛 0.125.0）；官方 `openai-codex` SDK 与 App Server 文档（实施时重新核对）。

- **集成方式（方案 A）**：SDK 负责进程与基础调用；流式事件与审批经 app-server 协议获取。
- **验证门禁（R3 前必须完成）**：确认 SDK 是否暴露底层 JSON-RPC 通道。能暴露则事件、审批与 SDK 调用共用一个连接；不能则回退为直连 app-server 协议，SDK 仅用于 CLI 版本锁定。回退须记录并告知用户，不静默切换。
- **版本**：SDK 与 CLI 版本一并锁定；启动时读取版本与 `initialize` 能力，不匹配则能力标记 `unsupported`。
- **会话**：平台 `session_id` ↔ Codex `thread_id`，记录在 `runtime_session_bindings`。`thread/resume` 恢复，`thread/fork` 分支，`thread/compact/start` 仅在平台压缩不可用时使用。
- **事件映射**：`item/agentMessage/delta` → `message.delta`；`item/started` / `item/completed`（命令、文件变更、动态工具）→ `tool.started` / `tool.completed`；审批请求 → `approval.requested`，平台决定后回复 `accept` / `acceptForSession` / `decline` / `cancel`；`acceptForSession` 必须先经 `action_grants` 批准；`thread/tokenUsage/updated` → `usage.updated`；`turn/completed` → 终态映射表。
- **取消**：`turn/interrupt`，收到 `interrupted` 终态后才结束 Run。`turn/steer` 默认 `unsupported`。
- **原生能力约束**：文件与 shell 通过 `Sandbox` 参数限制为 `workspace_write`，工作目录为平台分配的隔离工作区；多用户场景禁止 `full_access`。无法验证网络控制时能力标记 `unverified`，禁止绑定需要网络控制的技能。
- **平台工具**：经平台 MCP 服务暴露，每次调用携带短时运行令牌；平台复核权限，不信任模型传入的 workspace 或 user 标识。
- **传输**：只使用 stdio。WebSocket 为实验性，启用前必须配置鉴权。`-32001` 过载错误使用指数退避与抖动，并计入预算。

### 5.4 Claude Code 适配器

借鉴：官方 `claude-agent-sdk`（无开源参考实现）。**实施前必须读官方文档并锁定版本**，未核对的行为保持 `unverified`。

- **集成方式**：`ClaudeSDKClient`，支持自定义工具与 Python 回调钩子。
- **权限**：`can_use_tool` 回调作为审批入口，映射到 `approval.requested`。`allowed_tools` 只做自动批准、不隐藏工具，因此禁用原生工具必须用 `disallowed_tools`。
- **会话**：首次回复记录 session id；后续 `resume`；`fork_session` 用于分支。
- **系统提示**：SDK 在首次请求记录并复用，平台提示变化只在新会话生效。
- **原生工具**：Bash、Edit、Read 等必须通过 `disallowed_tools` 或 `can_use_tool` 限制；无法限制的工具不允许绑定到该 Runtime。
- **依赖**：本机需安装 Claude Code CLI，版本与 SDK 配套；账号与模型权限单独验证。

**切换规则（两种外部 Runtime 共同适用）**：切换 Runtime 时创建新会话或显式分支。平台将摘要、已授权消息与引用传给新 Runtime，不承诺迁移 SDK 内部状态。能力不足时界面显示差异；发布智能体时拦截不满足其绑定资源的组合。

### 5.5 工具与授权网关

借鉴：GenericAgent `ga.py`（`do_*` 分发、输出限制）；DeepSeek Harness `spill`（大输出落盘）；WeKnora `tools/` 与工具策略（每次调用复核）。

- **定义（ToolDefinition）**：名称、版本、JSON Schema（参数与结果投影）、风险等级、所需资源、副作用标记、幂等性标记、超时、所需 capability。
- **注册**：按名称与版本登记。处理器必须可协作取消；阻塞或资源密集的函数需要独立执行器或隔离后端。
- **ToolGateway（单调守卫）**：每次调用依次经过 schema 校验、当前授权查询（查数据库，不读快照）、风险分级、审批（如需）、执行、结果投影、审计。守卫只能收紧权限；模型不能通过参数选择主体、空间或 Run。
- **结果投影与 Spill**：工具作者提供公开结果投影，默认最多 4000 字符进入模型与事件；超过阈值的原始输出写入 run 级工件存储，上下文中只保留摘要与引用句柄。截断必须显式标注。
- **内置工具**：平台类（知识检索、记忆读取、检查点、待办、询问用户）；领域类（观澜，由领域包注册）；受控执行类（代码、文件、Web），仅在沙箱后端通过验收后开放（见 5.9）。

### 5.6 技能（Skill）

借鉴：Hermes `skills_guard.py`（来源检疫）、`skills_hub`（来源与安装）；DeerFlow `skills/`（projection 沙箱只读投射、security_scanner、mutations 审核修改）。

- **定义**：版本化的 `SKILL.md` 加资源文件，描述工作流程、何时调用哪些工具、输出格式。**技能不授予任何权限**。
- **版本**：SkillVersion 不可变，保存正文、资源、依赖（工具、MCP 工具、知识库）与内容哈希。草稿可改，发布生成新版本。
- **渐进披露**：默认只向模型提供名称与简介，正文按需加载，资源按需读取。
- **依赖校验**：发布智能体版本时检查技能依赖是否已由智能体绑定满足；缺失则拒绝发布并说明原因。
- **来源检疫**：内置技能可信；外部来源按信任级别决定，社区来源有任何发现即阻止，除非管理员明确放行。静态扫描覆盖可疑网络请求、凭据读取、文件写入目标与混淆代码；扫描只是门禁之一，运行时授权仍然有效。
- **自主修改**：模型可提交技能草稿，发布需审核（人工或规则），不得直接修改已发布版本。
- **与 Runtime 的关系**：Native 由平台加载指令与资源；Codex、Claude 将技能转换为指令，或在 SDK 支持时加载技能目录。转换方式在能力表中标明。

### 5.7 MCP

借鉴：WeKnora `approval/mcp_risk.go`（高风险 MCP 工具审批）。

- **客户端**：连接外部 MCP 服务，发现工具，按工具启用，不默认开放整个服务；凭据以引用保存。
- **服务端**：平台对外暴露已授权工具，供 Codex、Claude 等 Runtime 调用。
- **运行令牌**：短时令牌，与 Run 生命周期一致，单 Run 有效，撤销即失效；服务端每次调用复核权限。
- **高风险工具**：按风险等级要求审批，结果记录为 `action_approvals`。

### 5.8 记忆

借鉴：GenericAgent `memory/`（四层结构、SOP、写入约束）；Hermes `memory_tool.py`（冻结快照、用户画像）；DeerFlow `agents/memory/`（后端无关契约、prescreen 预筛、异步去抖）；TradingAgents `memory/log.py`（决策记录与事后回填）。

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

### 5.9 沙箱与执行环境

借鉴：DeerFlow `sandbox/`（lease 租约、虚拟路径、原子写入、文件锁）；Hermes `tools/environments/`（多后端）；DeepSeek Harness（接缝）；FastGPT `agent-sandbox`（容器镜像，仅参考）。

- **接缝**：`CommandExecutorPort`（命令执行）与 `FileStorePort`（文件读写与产物）。后端：`local`（仅开发模式，不能用于多用户）、`docker`（候选，R7 评估）、`ssh`（候选）。
- **租约**：执行方持有租约，到期或任务结束后回收；超时与取消释放租约。
- **虚拟路径**：模型看到 `/workspace`、`/outputs` 等虚拟路径，宿主路径由后端映射，不泄露宿主结构。
- **文件写入**：临时文件加原子替换；不对并发写入做仲裁。
- **产物**：记录为 Artifact，关联 Run 与来源；下载走授权检查。
- **门禁**：只有通过隔离验收的后端才能注册任意代码、shell、文件写入工具。验收项：CPU、内存、时间、输出大小限制；网络隔离；用户隔离；清理；崩溃后残留检查。未通过时工具不出现在工具列表中，而不是返回错误。
- **当前状态**：接缝契约已保留，能力标记 unavailable；没有任何可执行后端。

### 5.10 知识库

借鉴：RAGFlow `internal/agentic_rag/`（证据登记 `[ID:n]`、判断与断路、检索工具正交化）；WeKnora（先按权限过滤再检索，图谱按空间隔离）；FastGPT（数据集模型，仅参考）。

**存储**：PostgreSQL 保存知识库、文档、不可变文档版本、索引任务、文本块定位与引用关系；原文件走可替换的对象存储接口；向量索引由独立向量服务承载（R5 验证后确定）。

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

**证据登记**：检索结果进入上下文时登记为 `[ID:n]`，同一 Run 内去重；模型输出的引用必须指向已登记句柄，无效引用判为失败。

**图谱增强（可选，按知识库启用）**：
- 可单独开启图谱，配置实体类型、关系类型、抽取约束、归一规则与模型配置版本；schema 应窄而明确。
- 图元素记录知识库、文档版本、来源块、抽取时间与 schema 版本；原文块仍是证据事实源，图是可追溯的派生数据。
- 实体归一保守：不得仅凭名称相似合并不同公司、证券、人物或事件。
- 图谱写入按知识库与索引版本隔离，新版本构建完成后才切换可见。
- 图检索有界（种子实体、关系数、跳数、证据块、耗时、模型调用均有上限）；被截断时明确告知，不能把未返回的关系解释为"不存在"。
- 图服务超时或索引缺失时回退到基础检索并记录降级；权限拒绝不得回退为越权搜索。

**验收要点**：同一智能体可绑定多个知识库；无权的库与文档不通过向量或图谱路径泄漏；文档更新、删除、撤权与索引重建同步处理向量与图谱索引，旧版本不再被召回；基础检索不依赖图谱。

### 5.11 权限、授权与审批

借鉴：WeKnora `approval/`（gate、grants，会话级授权）、`types/agent_grant.go`（授权与配置哈希绑定）、`application/service/agent_share_scope.go`（共享智能体不扩大底层资源）；Hermes `tools/approval.py`（危险命令检测）。

**身份**：`Principal` 由认证适配器提供（`issuer + subject`）。首次访问映射为本地用户；禁用用户拒绝访问。开发模式使用固定单一主体，不信任请求头中的用户标识。

**空间与成员**：Workspace 是资源所属范围（参考 WeKnora Tenant）。`MembershipRecord` 保存角色；非成员返回 404，角色不足返回 403。

**三类授权严格分离**：

| 类型 | 含义 | 范围 |
|---|---|---|
| ResourceGrant | 空间之间显式共享资源 | 资源层 |
| ActionGrant | 用户对某类动作的可记忆授权，绑定 session 或 automation 作用域、配置哈希、风险等级、过期与撤销 | 动作层（计划表 `action_grants`） |
| ActionApproval | 单次审批决定 | 单个调用 |

Workspace 角色与资源共享不能替代 ActionGrant 或审批。共享智能体不扩大其底层资源的权限。

**执行时复核**：每次工具调用、检索和资源读取都重新查询成员、资源状态、绑定与授权。撤权在下一次调用时生效。

**审批流程**：高风险调用生成 `approval.requested`，进入 `waiting_approval`；决定后经 `approval.resolved` 继续或拒绝；决定与依据写入审计。

**危险命令检测**：作为审批触发条件，不作为唯一防线；检测结果与授权共同决定。

**审计**：工具调用、授权判断、审批、模型请求与资源访问都写入审计，包括主体、空间、Run、结果状态与时间。秘密不进入审计与事件。

### 5.12 会话、事件与持久化

**数据表**（取自代码中的 `__tablename__`）：

| 表 | 用途 |
|---|---|
| `users`、`workspaces`、`workspace_memberships` | 身份、空间与成员角色 |
| `agents`、`agent_draft_bindings`、`agent_versions`、`agent_resource_bindings` | 智能体、草稿绑定、不可变版本、资源绑定 |
| `platform_resources`、`resource_grants` | 资源登记与空间间显式共享 |
| `sessions`、`messages`、`session_checkpoints` | 会话、消息（assistant/tool 消息带内部 Runtime 元数据）、工作检查点 |
| `runtime_session_bindings` | 平台会话与外部 Runtime 会话 ID 的映射 |
| `runs`、`run_events`、`outbox_records` | 运行、事件（sequence 游标）、Outbox 队列 |
| `native_run_states`、`run_directives` | Native 预算累计与运行指令 |
| `run_input_requests`、`action_approvals` | 等待输入的问题与回答；单次审批 |
| `tool_invocations` | 工具调用记录（幂等键、副作用标记、结果状态） |
| `memory_drafts`、`memory_entries`、`memory_versions`、`context_summaries` | 记忆草稿、已发布条目与版本、上下文摘要 |
| `model_profiles`、`model_profile_versions`、`model_providers`、`provider_models`、`model_defaults`、`native_preferences` | 模型配置版本、供应商、默认与偏好 |
| `provider_credentials`、`credential_references` | 加密凭据与凭据引用 |
| `audit_records` | 审计记录 |

计划新增（未实现）：`action_grants`、`run_snapshots`（等待审批时的版本化快照）。

**队列**：PostgreSQL Outbox 表作为持久队列。Run 与 Outbox 记录在同一事务提交；worker 使用 `SELECT ... FOR UPDATE SKIP LOCKED` 领取，写入带过期时间的租约。队列语义为至少一次，由 Run 状态与幂等约束阻止重复执行。租约丢失后，结果未知的 Run 转为 `interrupted`，不自动重放副作用。

备选方案：Redis Streams 与数据库不在同一事务，需要持续对账；RabbitMQ 增加运维成本。当前规模不需要。复评条件：队列积压、数据库连接争用、Outbox 维护成本，或需要多类型消息路由。

**事件**：持久序号 `sequence` 作为 SSE 的 `id` 与 `Last-Event-ID` 游标；JSON 响应保留独立 `event_id`。先提交事件再投递。每页最多 500 条；SSE 名称为 `run.event`。等待或终态结束当前连接；浏览器重连不创建新 Run。

**输入回答**：`POST .../runs/{run_id}/input` 携带 `input_request_id`、回答与 `Idempotency-Key`；重复提交返回相同结果；回答继续同一 Run，预算累计。

**数据库**：PostgreSQL 为事实源，SQLAlchemy 2.x 与 psycopg 3。Alembic 迁移由发布或运维命令显式执行，不在 API 或 worker 启动时自动运行。API 与 worker 使用同步 Session；core 不暴露 ORM 类型。SQLite 仅用于隔离单元测试与迁移方言检查，不作为应用后端。

**连接配置**：`configs/nexus.toml` 的 `[database].url` 为默认来源，优先级为显式参数 > TOML > `NEXUS_DATABASE_URL`。API、worker 与 Alembic 共用解析逻辑，不自动加载 `.env`。

### 5.13 模型与凭据

借鉴：自研，无对应参考模块。

- **配置**：供应商记录归属 Workspace；`owner_user_id` 非空时仅该用户可用，为空时为空间共享。每个供应商有多个 ModelProfile，修改产生不可变版本。
- **协议**：`options.protocol` 必须显式设置（如 `openai_chat_completions`），不从供应商名称猜测。首个适配器使用锁定版本的 `openai` SDK 异步 Chat Completions 流；禁用 SDK 自动重试；工具执行后不重放整个回合。
- **凭据**：Key 通过 API 一次性接收，使用 Fernet 加密保存在独立凭据表。主密钥经环境注入 API 与 worker，不写入数据库或仓库。缺少主密钥或密文无效时拒绝解析，不回退为明文。
- **环境变量凭据**：`env://` 引用需同时登记在 `NEXUS_MODEL_CREDENTIAL_ALLOWLIST` 中，默认拒绝全部环境变量名。
- **网络出口**：HTTPX 调用经目的地址策略：默认只允许公网 HTTPS，检查 DNS 解析结果并固定 IP，保留 TLS/SNI 校验，禁用重定向，不使用环境代理。连接测试与正式调用共用同一策略。
- **默认与固定**：显式模型优先于个人默认，个人默认优先于空间默认。默认只用于新智能体选择，不改已发布版本与已有会话。个人模型在发布、会话创建和执行时都校验归属。
- **运维边界**：主密钥丢失则密文无法恢复，需纳入部署秘密管理备份；轮换需离线重加密，不提供自动轮换。停用供应商不撤回已发出的请求，之后的回合拒绝执行。
- **错误分类**：`model_authentication_failed`、`model_request_rejected`、`model_quota_exhausted`、`model_response_failed`、`timeout`、`rate_limited`、`provider_unavailable`、`context`、`stream`、`model_credential_unavailable`。供应商正文与认证信息不进入错误文本。
- **用量**：保留 input、output、cache_read、cache_creation 字段；total 按协议归一；缺失时估算。

### 5.14 渠道（connectors）

借鉴：LobeHub 渠道适配器的组织方式（`chat-adapter-*`）。

- 企业微信优先，随后微信、QQ。各渠道只做消息标准化与投递，不复制智能体循环。
- 渠道身份映射到平台用户（`ChannelIdentity`），渠道会话映射到平台会话（`ChannelSessionBinding`）。
- 去重、鉴权、回复长度限制与重试由渠道适配器处理。

### 5.15 Web 工作台

借鉴：自研。

- **技术**：Vue 3 + TypeScript + Element Plus，Node.js 22.12+。
- **界面约定**：浅色、扁平卡片、青绿色主色、系统字体，适配桌面与窄屏；键盘焦点可见、对比度达标、加载与错误有反馈、减少动态效果。规划功能显示"待接入"，不显示虚构的运行数据。
- **信息结构**：智能体管理、会话工作台、技能/工具/MCP 资源、知识库、渠道、设置、观澜工作台。类型标签展示能力来源；资源绑定同时显示兼容状态与版本。
- **安全**：模型输出按纯文本渲染，不作为 HTML 执行。
- **API**：`/api/v1/workspaces/{workspace_id}/...` 为当前接口。规划中的 `/agents`、`/skills`、`/knowledge-bases`、`/channels`、`/artifacts` 等尚未实现。观澜接口使用 `/api/v1/guanlan/...`。

### 5.16 观澜（股票研究，领域扩展）

借鉴：TradingAgents（分析员报告 → 多空辩论 → 研究经理综合；决策回填）；daily_stock_analysis（专业分工、分析深度分级、中间观点结构化，未深读）；Qlib（训练与推理分离，未深读）。

**数据边界**：结构化行情与财务（观澜数据服务）、研报与公告（知识库证据）、分析规则（专家审核的版本化规则）三者分开，互不替代。

**数据源**：通过 `guanlan/data` 适配器接入，智能体与技能只调用项目工具。候选数据源须逐接口验证覆盖市场、历史范围、更新频率、稳定性、使用条款与商业限制；不把"库中存在接口"当作 SLA 或授权保证。

**时点与来源**：每条数据保留 provider、获取时间、数据对应时间、复权与口径；无法确认的字段明确标记，不推断补齐。采集由 worker 定时调度。

**研究流程（候选，步骤 4、5、7、8 是否必选待 R9 确认）**：

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

**边界**：本节不表示当前仓库已实现数据采集、模型工具、辩论流程或回测。

---

## 6. 关键决策

| 编号 | 决策 | 状态 |
|---|---|---|
| D1 | 平台主库使用 PostgreSQL；SQLAlchemy 2.x + psycopg 3；Alembic 显式迁移，不自动建表 | 已采纳；PostgreSQL 专项待目标环境验收 |
| D2 | 队列使用 PostgreSQL Outbox + `SKIP LOCKED` 租约，至少一次语义 | 已采纳；并发与故障演练待验收 |
| D3 | Native 引擎独占循环；worker 装配模型、工具、持久化与取消 | 已实现 |
| D4 | 首个模型协议为 OpenAI Chat Completions，`protocol` 显式配置；禁用 SDK 自动重试 | 已实现；真实供应商待验收 |
| D5 | 工具必须显式绑定且实际调用时复核授权；模型不能选择主体 | 已实现 |
| D6 | 没有验收隔离后端时不注册任意代码与宿主文件工具 | 已实现 |
| D7 | 用户模型设置：Fernet 加密凭据，主密钥经环境注入；HTTPX 目的地址策略 | 已实现 |
| D8 | Memory/SOP 只产生待审核草稿，不自动注入提示 | 已实现 |
| D9 | Codex 采用 `openai-codex` SDK 管进程，事件与审批经 app-server 协议；R3 前验证 SDK 通道，不通过则回退直连 | 已确认，验证待执行 |
| D10 | Claude Code 采用 `claude-agent-sdk` 封装 | 已确认，官方文档核对待执行 |
| D11 | Native 迁移采用"等价翻译 + 按职责拆分"，不采用单文件保留 | 已确认 |
| D12 | 沙箱后端验收前，Native 不提供任意代码执行 | 已确认 |
| D13 | 观澜股票研究为最后一期（R9） | 已确认 |
| D14 | 真实账号与数据源在对应实施阶段由用户提供 | 已确认 |
| D15 | 参考项目只借鉴设计并按需等价翻译；每个模块在第 2 节标明借鉴来源 | 已确认 |

---

## 7. 测试与评估

- **软件回归**：`tests/`，覆盖平台、Native、工具、配置、迁移与前端。
- **契约测试**：同一组用例（文本流、多工具、审批拒绝、取消、超时、崩溃后恢复）在 Native、Codex、Claude 上运行，断言统一终态与事件序列。
- **行为矩阵**：GenericAgent 与 WeKnora 的关键行为逐条映射到测试（R2 建立，记录位于 `packages/runtimes/docs/`）。
- **安全测试**：越权调用、撤权后的下一次调用、运行令牌过期、原生工具禁用、秘密不进入事件与审计。
- **智能体与检索评估**：`evals/`，固定任务、检索引用正确率、技能选择准确率、运行能力契约。
- **策略回测**：观澜 `guanlan/backtesting`，与软件回归分开记录输入版本、结果和失败原因。
- **集成环境**：PostgreSQL 与真实供应商在目标环境执行。未执行的部分在交付说明中列明。

---

## 8. 参考仓库与许可证

参考仓库位于 `/project/opensource/`，固定版本如下。

| 项目 | commit | 许可证状态 |
|---|---|---|
| GenericAgent | `a9a36b4` | MIT（已读取根许可证） |
| WeKnora | `e1f9a6166` | MIT，含第三方许可说明（已读取根许可证） |
| Hermes Agent | `eb1b4c5b61` | 迁移代码前须核对 |
| RAGFlow | `e5a5060c4` | 迁移代码前须核对 |
| DeerFlow | `a1b89d0` | 迁移代码前须核对 |
| FastGPT | `749809070` | 迁移代码前须核对 |
| TradingAgents | `e8f5503` | 迁移代码前须核对 |
| DeepSeek Harness | `22ddee3792` | 迁移代码前须核对 |
| LobeHub | `e1d7bc5655` | 迁移代码前须核对 |
| AutoGen | `d07c667` | 仅借鉴设计，须核对许可证 |
| CrewAI | `97bbfb6` | 仅借鉴设计，须核对许可证 |
| AutoGPT | `07212df` | 仅借鉴设计，须核对许可证 |
| Dify | `dcb33269` | 仅借鉴设计，须核对许可证 |
| LangFlow | `b5c54a6` | 仅借鉴设计，须核对许可证 |
| n8n | `a9874246` | 仅借鉴设计，须核对许可证 |
| OpenClaw | `7293e892` | 仅借鉴设计，须核对许可证 |

原则：不提交整个第三方仓库；只迁移适用许可证的代码片段，并在模块文件头或包内文档保留来源、版本和许可声明。非 MIT/Apache 项目仅借鉴设计，不复制代码。

---

## 9. 运行约束

- 运行提交与输入回答要求 `Idempotency-Key`；同一键重复提交返回原结果。
- 长任务不在 HTTP 请求中执行；提交即返回 Run，状态通过事件与游标读取。
- 启动、迁移与配置错误必须以可读信息失败，不输出凭据。

---

## 10. 当前实际能力

已实现：
- `/api/v1/health`、PostgreSQL 连通检查 `/api/v1/ready`、运行时能力接口 `/api/v1/runtime-capabilities`。
- 身份与空间、成员角色、模型配置版本、Agent 草稿与发布、固定版本 Session、幂等 Run、事件 JSON 与 SSE 续读、Outbox 队列、审计。
- Native 引擎：流式文本、授权 Python 工具、预算、取消、等待输入、检查点、有界历史摘录、Memory/SOP 草稿。
- 用户模型供应商设置、个人与空间范围、加密 Key、默认模型与有界连接测试。
- Web：空间、智能体与会话选择、对话、工具状态、停止与游标重连。
- 配置：`configs/nexus.toml` 数据库配置，API、worker、Alembic 共用。

未实现（不得宣称可用）：
- 真实身份提供方（开发模式之外）、外部凭据保险库。
- Codex 与 Claude Code 适配器。
- 技能、MCP、知识库的执行（当前 Native 遇到这些绑定时明确失败）。
- 隔离沙箱后端、文件产物。
- 观澜数据、分析与回测。
- 渠道接入。
- 运行快照与 ActionGrant（`action_grants`）等计划表。
- 第 4.2 节的目录调整。

验证边界：SQLite 与模拟模型验证通过；PostgreSQL 并发、迁移与故障恢复未在目标环境验收；真实供应商未在线验收；浏览器测试使用 API 与 SSE 夹具，不是完整部署环境的端到端验收。
