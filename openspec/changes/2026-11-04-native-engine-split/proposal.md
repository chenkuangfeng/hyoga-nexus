# Native 引擎拆分：运行时契约与组件边界（路线图 3.3–3.9）

## 状态

已确认（按推荐方案，见第 6 节）。实施状态见 tasks.md。

**2026-11-04 实施前核对的更正**：第一版草稿中有三处与代码不符，已按实际情况修正，见第 7 节。

## 原因

`packages/runtimes/src/nexus_runtimes/native/engine/runner.py` 的 `NativeEngine` 是一个约 260 行的编排类，同时负责运行生命周期、取消、预算、事件持久化、回合循环和恢复。模型协议、完成判断、上下文、钩子和工具已经分在独立模块中，但它们之间的边界由 `NativeEngine` 隐式约定，没有显式契约：

- 运行时没有统一的端口。`nexus_core.contracts.AgentRuntime`（`stream(AgentRequest) -> AgentEvent`）是旧协议，代码中没有实现也没有调用方，与路线图 3.3 的 `AgentRuntime` 端口同名但语义不同。
- 工具定义已有 `version`、`side_effects`、`timeout_seconds`、`capability` 字段，但没有风险等级、幂等标记和所需能力，网关复核的依据不完整。
- 完成判断分散在 `completion.py` 与 `runner.py` 的分支中，截断续写、空响应重试、停滞判定没有统一的判定结果类型。
- 外部 Runtime（路线图第 4 步 Codex）接入时，没有可以对齐的 `RunRequest`、`RunContext`、`RuntimeCapabilities` 契约，只能复制 `NativeEngine` 的内部细节。

本提案把现有行为拆成路线图 3.3–3.9 描述的组件，并把契约显式化。**不改变对外行为**：API 契约、事件类型与顺序、持久化结构、配置项都保持不变。

## 现状核对（2026-11-04）

| 路线图项 | 现状 |
| --- | --- |
| 3.3 运行时契约 | `nexus_core.contracts.AgentRuntime` 为旧协议，无调用方；`nexus_core.runtime` 中有 `ExecutionBudget`、`RuntimeOutcome`、`RuntimeProgress`、`ToolDefinition`、`ToolGatewayPort`。`RunEvent` 在 `nexus_core/platform.py`。 |
| 3.4 编排 | `NativeEngine.run` 承担编排；worker 在 `apps/worker/src/nexus_worker/native.py:184` 直接构造。 |
| 3.5 回合执行 | `engine/turn.py` 的 `collect_response` 与 `DeltaBuffer` 已分离，回合循环仍在 `runner.py`。 |
| 3.6 上下文 | `context/` 下已有 `history`、`working`、`compaction`、`assembly`，尚无统一装配入口与"Run 内冻结"保证。 |
| 3.7 完成判断 | `engine/completion.py` 的 `CompletionPolicy.evaluate` 返回 `CompletionVerdict`，但重试与续写分支仍在 `runner.py`。 |
| 3.8 工具调度 | `engine/tools.py` 的 `execute_batch` 与 `engine/recovery.py` 的 `resume_tools` 已存在；`policy.parallel_reads` 默认 `True`，`runner.py` 调用处传入该值；大输出外置（P2）已实现：网关 `_externalize`、存储 `read_tool_output`、读取工具 `read_tool_output`。 |
| 3.9 工具定义与网关 | `ToolDefinition` 已有 `read_only`、`idempotent`、`requires_approval`、`side_effects`、`timeout_seconds`、`capability`、`version`；缺少 `risk_level` 与 `required_capabilities`。`ToolGatewayPort` 已存在。 |

## 范围

范围内：

1. **3.3 契约**（`nexus_core/runtime/`）：
   - `RunRequest`（会话、Agent 版本、消息、预算）、`RunContext`（主体、租约 epoch、取消令牌、存储端口）、`RuntimeCapabilities`（是否支持流式、工具、等待输入、恢复、取消）。
   - `AgentRuntime` 端口：`capabilities()` 与 `async run(request, context) -> RuntimeOutcome`。
   - `RunEvent` 类型化：引擎内部使用的事件结构，与现有 `run_events` 的字段一一对应，不改变持久化格式。
2. **3.4 `RunOrchestrator`**（`engine/orchestrator.py`）：生命周期、取消、预算计数、事件持久化、租约检查。从 `NativeEngine.run` 中拆出；`NativeEngine` 保留为兼容门面，实现 `AgentRuntime`。
3. **3.5 `TurnExecutor`**：组装单回合请求、调用模型、收集流式响应、解析为 `TurnResult`（文本、工具调用、结束原因、用量）。复用 `collect_response`。
4. **3.6 `ContextAssembler`**：统一入口，合并 `context/` 下的装配逻辑。Run 开始时冻结系统前缀与工具 schema 的哈希，Run 内任何回合若发现变化则显式失败（不静默改写）。压缩结果作为事件写入。
5. **3.7 `CompletionJudge`**：把 `CompletionPolicy` 扩展为返回明确的判定枚举：`accept`、`continue_truncated`、`retry_empty`、`stalled`、`incomplete_tool_call`（不执行）、`final_without_tools`（最后一轮禁用工具）。`runner.py` 只根据枚举分派。
6. **3.8 `ToolDispatcher`**：合并 `execute_batch` 与 `resume_tools` 的调度逻辑；执行前做 schema 校验与网关复核；按声明顺序执行；`side_effects=True` 的工具不并发；结果投影为模型可见的摘要。大输出外置（Spill）接口在本提案中定义，实现复用已有机制，若已有机制不足则拆出到后续任务（见第 6 节第 6 条）。
7. **3.9 工具定义扩展**：`ToolDefinition` 增加 `risk_level`（`low`/`medium`/`high`，默认 `medium`）、`idempotent`（默认 `False`）、`required_capabilities`（默认空元组）。新字段均有默认值，既有工具注册不需要修改。`ToolGatewayPort` 的方法签名不变。
8. **行为保护**：在重构前为既有场景录制事件序列基线（文本流、多工具、审批拒绝、取消、超时、等待输入后恢复），每一步重构后基线必须一致。这是路线图 3.16 的子集，3.16 的完整契约测试仍在第 3 阶段后期完成。

范围外（明确不做）：

- 3.10 内置平台工具（待办、工作检查点更新的新规则）、3.11 记忆接入、3.12 技能加载。
- 3.13–3.15 的取消细化、挂起恢复加固、预算四维计数与钩子改造。本提案只搬迁现有逻辑，不改变其语义。
- 3.21 性能验收与默认值调整。
- 第 4 步 Codex 适配器，以及 3.24 异步工具。
- 沙箱接入、外部 Runtime 实现。
- 任何 API 路由、数据库迁移、前端改动。

## 接口与兼容性

- **对外 API**：无变化。
- **事件**：类型与顺序不变；基线测试强制保证。
- **持久化**：无迁移。`ToolDefinition` 新增字段不写入数据库；若工具定义需要持久化，另行提案。
- **配置**：无新增配置项。
- **worker 装配**：`apps/worker/src/nexus_worker/native.py` 仍然构造 `NativeEngine`，直到本提案最后一步才切换到 `RunOrchestrator`。
- **旧协议**：`nexus_core.contracts.AgentRuntime` 按第 6 节第 1 条处理。

## 重构顺序（每步独立可回滚）

1. 录制事件序列基线（测试先行，不改生产代码）。
2. 新增契约类型与 `ToolDefinition` 字段（纯新增，无调用方变化）。
3. 抽出 `ToolDispatcher`，`runner.py` 改为调用它。
4. 抽出 `CompletionJudge` 的判定枚举，`runner.py` 改为按枚举分派。
5. 抽出 `TurnExecutor`。
6. 抽出 `ContextAssembler`，并加入 Run 内前缀冻结断言。
7. 抽出 `RunOrchestrator`，`NativeEngine` 变为门面，worker 切换构造方式。
8. 清理旧协议与死代码，更新 `packages/runtimes/docs/design.md`。

## 已确认的决定

以下为推荐方案，等待确认后才能编码：

1. **旧协议**：删除 `nexus_core.contracts.AgentRuntime`（无调用方），由新的 `AgentRuntime` 端口替代。替代方案是保留旧协议并改名，但会长期产生歧义。
2. **`NativeEngine` 门面**：在第 7 步之前保留，切换 worker 后在同一提案内删除，不跨提案保留。
3. **风险等级**：只用 `low`、`medium`、`high` 三档，不引入数值评分。（已确认）
4. **并发策略**：保持当前默认顺序执行；只有 `side_effects=False` 且未显式声明串行的工具可并发。需先核对 `execute_batch` 的实际调用处是否传入了 `parallel=True`。
5. **基线测试**：本提案包含录制基线，它是重构的安全网，不等到 3.16 再做。
6. **大输出外置（Spill）**：先核对 `builtins/tool_output.py` 与现有存储是否已满足需求。若已满足，本提案只定义接口；若不满足，Spill 的实现拆到单独的后续提案，不在本提案内扩大范围。（核对结果：已满足，本提案只复用，不改实现。）

## 验收

- 既有 Native 测试（`tests/test_native_*.py`、`tests/test_run_*.py`、`tests/test_session_ledger.py`、`tests/test_dispatch_ledger_integration.py`、`tests/test_context_placement.py`、`tests/test_compaction_policy.py`）全部通过；本次核对时基线为 101 个通过。
- 录制的事件序列基线在每一步后保持一致。
- 每个新组件有独立单元测试：`ToolDispatcher`（顺序、并发限制、网关复核、schema 校验）、`CompletionJudge`（六种判定）、`ContextAssembler`（前缀冻结断言）、`TurnExecutor`（流式收集与解析）。
- `NativeEngine` 门面在第 7 步之后删除，`grep` 中不再有 `NativeEngine` 的生产引用。
- `packages/runtimes/docs/design.md` 与 `docs/architecture.md` 的 Runtime 章节同步更新。

## 依赖

- 依赖 2.12 会话快照与 3.1 基础闭环（均已完成）。
- 不依赖 3.10 以后的项。3.10–3.16 可以在本提案完成后再做，避免它们在拆分过程中同时改动同一批文件。

## 影响

- 代码：`packages/core`（契约与工具定义）、`packages/runtimes`（引擎）、`apps/worker`（构造处）。
- 文档：路线图 3.3–3.9 在验收后勾选；本提案归档时同步规格。

## 7. 实施前核对的更正（2026-11-04）

1. **3.9 字段**：`idempotent` 与 `read_only`、`requires_approval` 已存在于 `ToolDefinition`，不再新增。本提案只新增 `risk_level`（默认 `medium`）与 `required_capabilities`（默认空元组）。
2. **3.8 大输出外置**：已实现（P2）。本提案不改动其实现，只保证调度器在结果投影时保留既有的外置行为。
3. **3.7 判定枚举**：草稿中的 `continue_truncated` 与 `final_without_tools` 与现有行为不一致。现有实现中，文本被截断（`finish_reason=length`）时是直接接受并发出 `answer.truncated`，并没有续写；"最后一轮禁用工具"也不存在。纯重构只能保留现有行为，因此枚举改为：`accept`、`accept_truncated`、`retry_empty`、`stalled`、`fail`、`incomplete_tool_call`（不执行，计入截断计数）。续写与最后一轮禁用工具属于新行为，另行提案，不在本次范围内。
4. **运行时事件类型名**：`nexus_core.platform.RunEvent` 已被平台层占用。引擎内部的类型命名为 `RuntimeEvent`，只在契约层使用，不改变 `run_events` 的持久化结构。
5. **行为基线**：`tests/test_native_engine_golden.py` 记录了六个场景（文本回答、多工具、无效参数后回答、截断工具调用后回答、空响应重试、等待输入）的事件类型序列、终态与工具状态，基线取自提交 `d32b48d`。
