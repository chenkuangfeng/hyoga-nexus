# Proposal: P2 自研 Native 智能体闭环

## Why

P1 已提供 Workspace 授权、不可变 AgentVersion、Session、Run/Event 和 PostgreSQL worker，但 worker 目前会以 `runtime_not_configured` 结束 Run。P2 为平台补上可流式对话、调用已授权 Python 工具、续读事件和停止运行的 Native Runtime，同时保留 GenericAgent 的核心执行语义与扩展能力。

## What Changes

- 新增平台调用的 Native Runtime Engine、厂商无关模型流契约和首个 OpenAI-compatible 模型适配器。
- 增加多轮模型/工具处理、StepOutcome 等价语义、预算、超时、取消、waiting_input、持久事件和 SSE 续读。
- 增加 Session 历史、工作检查点、工具生命周期钩子、受控工具注册/授权网关，以及记忆/SOP 待审核草稿扩展点。
- 在 Vue 3/TypeScript/Element Plus 中增加对话工作台，展示流式消息、工具运行、等待输入、失败/取消和重连状态。
- 定义 SandboxPort；未配置和验收隔离执行后端时，不提供任意 shell、Python eval 或任意网络工具。
- 修改 P1 Run 的 Native 执行行为，使 worker 能装配 Native Runtime；P1 的 PostgreSQL 专项验收仍单独追踪。

## Capabilities

### New Capabilities

- `native-agent-runtime`: Native 模型/工具执行、生命周期、上下文、取消与安全能力。
- `run-streaming`: 持久 Run 事件、SSE 续读、对话工作台和停止/等待状态。

### Modified Capabilities

无。当前 `openspec/specs/` 中没有已发布能力规格；P2 新增的 worker Runtime 分派行为由 `native-agent-runtime` 规格定义。

## Impact

- 代码：`packages/core`、`packages/runtimes/native`、`packages/tools`、`packages/sandbox`、`packages/platform`、`apps/api`、`apps/worker`、`apps/web`。
- 持久化/API：Assistant 与工具消息、运行钩子/检查点、等待输入命令、SSE 事件和 Runtime 执行状态。
- 依赖：拟增加已核对并锁定的异步模型 SDK；具体版本须在实施前验证。当前不引入 MCP、知识库或外部 Runtime 依赖。
- 限制：任意代码执行依赖经过安全验收的 Sandbox backend；没有该后端时 Native 只运行显式登记的 Python 工具。

## 审核边界

用户已于 2026-10-25 明确要求继续 P2 代码实现。本轮完成 Native 闭环与 SQLite/模拟模型/浏览器夹具验证；真实供应商、PostgreSQL 和隔离后端验收边界见 [验收记录](verification.md)。
