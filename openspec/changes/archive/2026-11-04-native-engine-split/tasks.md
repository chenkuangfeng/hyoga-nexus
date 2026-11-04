# 任务：Native 引擎拆分（路线图 3.3–3.9）

> 状态：已实施并通过测试（后端全量 647 通过、1 跳过）。`[x]` 表示已完成并验证，`[ ]` 表示未完成。
> 与原计划不同之处见 proposal.md 第 7 节与各条的"说明"。

## 1. 前置

- [x] 1.1 确认 proposal.md 第 6 节的六项决定（已确认，推荐方案）。
- [x] 1.2 核对 `execute_batch` 的并发参数：`policy.parallel_reads` 默认 `True`，编排器调用处传入该值。
- [x] 1.3 核对大输出外置：已实现（P2），本次只复用，不改实现。
- [x] 1.4 核对 worker 构造点：`apps/worker/src/nexus_worker/native.py`。

## 2. 行为基线

- [x] 2.1 录制六个场景的事件序列基线（文本回答、多工具、无效参数后回答、截断工具调用后回答、空响应重试、等待输入）。
- [x] 2.2 基线以测试固化（`tests/test_native_engine_golden.py`），只比较事件类型、终态和工具状态，不比较时间戳与 ID。
- [x] 2.3 基线在改动生产代码前通过（提交 `7341f99`）。

## 3. 契约

- [x] 3.1 `nexus_core/runtime/port.py`：`RuntimeCapabilities`、`RunRequest`、`RunContext`、`AgentRuntime` 端口。
  - 说明：`RunEvent` 未引入。事件仍以 `(kind, payload)` 经存储端口传递，改动存储端口需另行提案。
- [x] 3.2 删除 `nexus_core.contracts` 中无调用方的旧 `AgentRuntime`、`AgentRequest`、`AgentEvent`。
- [x] 3.3 `ToolDefinition` 新增 `risk_level`（低/中/高，默认中）与 `required_capabilities`（默认空），非法风险等级拒绝构造。
  - 说明：`idempotent` 已存在，未重复新增。
- [x] 3.4 契约单元测试（默认值、非法值、不可变性、编排器满足端口）：`tests/test_native_engine_components.py`。

## 4. 组件拆分

- [x] 4.1 `ToolDispatcher`（`engine/dispatcher.py`）：结果投影、审批挂起、错误预算、终态与续写。
  - 说明：参数 schema 校验由工具网关完成（`nexus_tools/gateway`），调度器不重复校验。
  - 说明：`recovery.resume_tools` 未合并，保留独立的结果映射（与普通回合不同，合并会改变行为）。
- [x] 4.2 `CompletionJudge`（`engine/completion.py`）：六类判定 + 执行工具/失败的枚举。
  - 说明：判定枚举与现有行为对齐（见 proposal.md 第 7 节第 3 条）。截断续写与最后一轮禁用工具属于新行为，未实现，路线图 3.7 保持未完成。
- [x] 4.3 `TurnExecutor`（`engine/turn.py`）：组装请求、调用模型、收集流式响应。预算计数与 model 钩子仍在编排器。
- [x] 4.4 `ContextAssembler`（`context/assembler.py`）：压缩（在 turn.before 钩子之前）、回合视图（之后）、工具定义冻结与校验。
- [x] 4.5 `RunOrchestrator`（`engine/orchestrator.py`，由 `runner.py` 迁移并改名）：实现 `AgentRuntime`。
  - 说明：`NativeEngine` 直接改名，没有保留兼容门面。worker 与测试引用均已同步，因此门面没有存在的必要（与提案第 6 节第 2 条的"先保留门面"略有不同，结果一致：生产代码中不再有旧名字）。
- [x] 4.6 大输出外置：沿用既有机制，本提案不改动。

## 5. 切换与清理

- [x] 5.1 worker 通过 `RunRequest` + `RunContext` 调用 `RunOrchestrator.run`。
- [x] 5.2 `NativeEngine` 名称在生产代码与测试中已无引用（`grep` 确认）。
- [x] 5.3 删除编排器中不再使用的 `_message_bytes`（迁移到 `context/assembler.py`）与未使用的导入。

## 6. 测试

- [x] 6.1 `ToolDispatcher`：顺序结果、续写收集、审批挂起保留剩余调用、等待输入后其余调用标记未执行、COMPLETE 的映射、错误预算耗尽。
- [x] 6.2 `CompletionJudge`：执行工具、截断工具调用不执行并在上限后停滞、空响应重试与耗尽失败、接受、接受截断、内容过滤、重复停滞。
- [x] 6.3 `TurnExecutor`：由既有集成测试与基线覆盖（流式收集、截断、解析），未单独写单元测试，因为其逻辑只是转发给 `collect_response`。
- [x] 6.4 `ContextAssembler`：冻结后定义变化显式失败、视图预算包含定义大小、消息字节估计。
- [x] 6.5 `RunOrchestrator`：由既有集成测试覆盖（预算耗尽、取消、租约、等待输入后的恢复、模型超时不重放）。
- [x] 6.6 全量后端测试通过：647 通过、1 跳过。
- [x] 6.7 基线测试在每个重构步骤后保持一致（最终状态下仍然通过）。

## 7. 文档与收尾

- [x] 7.1 `packages/runtimes/docs/design.md` 更新组件边界与契约说明。
- [x] 7.2 `docs/architecture.md`：已核对，引擎目录描述仍然准确，无需改动。
- [x] 7.3 路线图 3.3–3.6、3.8、3.9 勾选；3.7 保持未勾选（截断续写、最后一轮禁用工具未做）。
- [x] 7.4 OpenSpec：本提案无已有规格文件需要同步（`openspec/specs` 中没有 runtime 规格）。提案归档至 `openspec/changes/archive/2026-11-04-native-engine-split`。
