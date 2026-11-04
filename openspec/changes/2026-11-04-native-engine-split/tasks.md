# 任务：Native 引擎拆分（路线图 3.3–3.9）

> 状态：草稿，待确认 proposal.md 第 6 节的决定。`[x]` 表示已完成并验证，`[ ]` 表示未完成。

## 1. 前置（确认后执行）

- [ ] 1.1 确认 proposal.md 第 6 节的六项决定。
- [ ] 1.2 核对 `execute_batch` 的所有调用处是否传入 `parallel=True`，记录结果。
- [ ] 1.3 核对 `builtins/tool_output.py` 与现有存储是否满足大输出外置需求，决定 Spill 是否在本提案内实现。
- [ ] 1.4 确认 `apps/worker/src/nexus_worker/native.py` 中的构造方式，列出需要改动的调用点。

## 2. 行为基线（先于任何生产代码改动）

- [ ] 2.1 录制事件序列基线：文本流、多工具、审批拒绝、取消、超时、等待输入后恢复六个场景。
- [ ] 2.2 基线以测试形式固化，断言事件类型与顺序，不断言时间戳和 ID。
- [ ] 2.3 在未改动生产代码的状态下，基线测试全部通过。

## 3. 契约（纯新增）

- [ ] 3.1 `nexus_core/runtime/` 新增 `RunRequest`、`RunContext`、`RuntimeCapabilities`、`AgentRuntime` 端口与 `RunEvent` 类型。
- [ ] 3.2 删除 `nexus_core.contracts.AgentRuntime`（按确认的决定第 1 条）。
- [ ] 3.3 `ToolDefinition` 增加 `risk_level`、`idempotent`、`required_capabilities`，全部带默认值。
- [ ] 3.4 契约类型的单元测试：默认值、非法值拒绝、不可变性。

## 4. 组件拆分

- [ ] 4.1 `ToolDispatcher`：合并 `execute_batch` 与 `resume_tools`；schema 校验；网关复核；顺序执行；`side_effects=True` 不并发；结果投影。`runner.py` 改为调用。
- [ ] 4.2 `CompletionJudge`：`CompletionPolicy` 返回六种判定枚举；`runner.py` 按枚举分派，移除内联分支。
- [ ] 4.3 `TurnExecutor`：封装单回合请求组装、模型调用与 `collect_response`，返回 `TurnResult`。
- [ ] 4.4 `ContextAssembler`：统一 `context/` 装配入口；Run 开始时冻结系统前缀与工具 schema 哈希；回合间发生变化时显式失败。
- [ ] 4.5 `RunOrchestrator`：生命周期、取消、预算计数、事件持久化、租约检查。`NativeEngine` 变为门面并实现 `AgentRuntime`。
- [ ] 4.6 大输出外置（Spill）：按 1.3 的决定实现或仅定义接口。

## 5. 切换与清理

- [ ] 5.1 worker 改为通过 `RunOrchestrator` 或 `AgentRuntime` 端口构造运行时。
- [ ] 5.2 删除 `NativeEngine` 门面与其中的旧分支，`grep` 确认无生产引用。
- [ ] 5.3 删除不再使用的内部函数与模块，保留的文件只包含新职责。

## 6. 测试

- [ ] 6.1 `ToolDispatcher`：顺序执行、副作用工具不并发、网关复核拒绝、schema 校验失败。
- [ ] 6.2 `CompletionJudge`：六种判定各一个用例，含"不完整工具调用不执行"与"最后一轮禁用工具"。
- [ ] 6.3 `TurnExecutor`：流式收集、截断、空响应、解析失败。
- [ ] 6.4 `ContextAssembler`：前缀冻结、回合间变化触发显式失败。
- [ ] 6.5 `RunOrchestrator`：取消、预算耗尽、租约失效、事件持久化顺序。
- [ ] 6.6 既有 Native 测试全部通过（基线：101 个通过，见 proposal.md 验收节）。
- [ ] 6.7 每一步重构后事件序列基线保持一致。

## 7. 文档与收尾

- [ ] 7.1 `packages/runtimes/docs/design.md` 更新组件边界与契约说明。
- [ ] 7.2 `docs/architecture.md` Runtime 章节同步。
- [ ] 7.3 路线图 3.3–3.9 按实际完成情况勾选，未完成项保留未勾选并注明原因。
- [ ] 7.4 OpenSpec 规格同步与归档。
