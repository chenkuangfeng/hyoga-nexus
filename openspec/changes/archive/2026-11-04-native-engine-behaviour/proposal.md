# Native 引擎行为补齐：截断续写、最后一轮禁用工具、待办、模型尝试预算（路线图 3.7 残余、3.10、3.13–3.15 核实）

## 状态

已实施，已归档。确认的决定见第 6 节；实施结果与偏差见 tasks.md。

偏差说明：`max_model_attempts` 的 0 表示由 `max_rounds * (model_retries + 1)` 推导（与上文默认值等价，但保存为 0 以便随配置变化）；模型尝试计数通过 `RetryModel.bind_attempts` 的鸭子类型钩子注入；最后一轮若模型仍返回工具调用，一律记为 "Not executed" 而不执行。

## 原因

`2026-11-04-native-engine-split` 已完成结构拆分，但路线图第 3 阶段仍有几项行为缺口：

- 3.7：文本被截断（`finish_reason=length`）时，引擎直接接受并标记 `answer.truncated`，没有续写；模型可以在最后一轮仍然调用工具，结束前没有"只能作答"的约束。
- 3.10：内置平台工具缺少待办（todo）。检查点与 `ask_user` 已存在。
- 3.15：回合、token、活跃耗时、错误四个维度已计数，但模型尝试次数没有计入 `progress`，`RetryModel` 的重试对预算不可见。
- 3.13、3.14：取消与等待输入的基础已有测试。恢复前的快照版本、会话与主体、Agent 与模型版本校验，尚未逐项核实。

## 现状核对

| 路线图项 | 现状 |
| --- | --- |
| 3.7 截断续写 | 未实现。`CompletionJudge` 对截断文本返回 `ACCEPT_TRUNCATED`，编排器发出 `answer.truncated` 并结束。 |
| 3.7 最后一轮禁用工具 | 未实现。每一轮都传入完整的工具定义。 |
| 3.10 检查点规则 | 已实现：`update_working_checkpoint` 只在成功结果时更新（`orchestrator.py` 与 `dispatcher.py`）。 |
| 3.10 等待输入 | 已实现：`ask_user` 产生 `WAIT_INPUT`。 |
| 3.10 待办 | 未实现：`packages/tools` 中没有 todo 工具。 |
| 3.13 取消 | 模型流与工具调用处已检查令牌。沙箱等待点不存在，待沙箱接入。 |
| 3.13 等待后幂等继续 | 已有测试（`test_waiting_input_checkpoint_and_memory_draft_are_durable` 等）。 |
| 3.14 挂起恢复校验 | 审批使用 `config_snapshot` 的哈希（`platform/runs/approvals.py`），授权在历史投影时复核（`messages.py`）。快照版本、会话、主体的逐项校验未核实，本提案第一步先核实，结果写入 tasks.md。 |
| 3.15 回合/token/活跃耗时/错误 | 已计数（`progress`），`asyncio.timeout` 使用活跃耗时。 |
| 3.15 模型尝试 | 未计数。`models/retry.py` 的 `RetryModel` 在内部循环重试，编排器不可见。 |
| 3.15 钩子 | 已实现：`LifecycleEvent` 只含 run_id、阶段、回合、工具名，异常在 1 秒超时内隔离并记 `hook.failed`。 |

## 范围

范围内：

1. **截断续写（3.7）**：文本被截断时，追加一条用户提示让模型从截断处继续，最多 `policy.max_continuations` 次（推荐默认 2）。每次续写发出 `answer.continued` 事件。超过上限后仍按现有方式接受截断答案并发出 `answer.truncated`。
2. **最后一轮禁用工具（3.7）**：当本回合是 Run 的最后一个允许回合（`progress.turns == budget.max_rounds`）时，本次模型请求的工具定义为空，并在上下文中加入一条"请直接给出最终答案"的提示。事件 `turn.tools_disabled` 记录。
3. **待办工具（3.10）**：新增内置工具 `todo`，支持 `list`、`set`（整体替换）两种操作，状态只存于 Run 的 `progress.state`，随 Run 结束释放。它不写入会话级持久化表，因此不需要迁移。跨 Run 持久化另行提案。
4. **模型尝试计数（3.15）**：`RetryModel` 每次实际发起的请求计入 `progress.model_attempts`（持久化到 `progress`），并发出 `model.attempt` 事件（含尝试序号，不含请求内容）。新增预算字段 `max_model_attempts`，默认值为 `max_rounds * (model_retries + 1)`，对已发布的 Agent 等价于不限制。
5. **挂起恢复核实（3.14）**：只读核实恢复路径的校验项，并把结果写入 tasks.md。若发现缺口，本提案不修复，另开提案。
6. **测试**：每项行为一个测试；`test_native_engine_golden.py` 的基线保持不变（这些新行为只在被截断、最后一轮、或新增工具时出现，既有场景不应有差异）。

范围外：

- 3.11 记忆接入、3.12 技能加载（依赖第 6、7 步）。
- 3.16 完整契约测试（在本提案之后统一补充）。
- 3.21 性能验收与默认值调整。
- 沙箱等待点的取消检查（依赖沙箱接入）。
- 待办的跨 Run 持久化与前端展示。
- 3.24 异步工具与推测执行。

## 接口与兼容性

- **事件**：新增 `answer.continued`、`turn.tools_disabled`、`model.attempt`。既有事件类型与顺序不变。旧客户端忽略未知事件类型。
- **预算**：新增 `max_model_attempts`。对已发布 Agent，默认值保证不改变行为；Agent 发布校验需要接受该字段（若 Agent 发布接口对预算字段有白名单，需同步）。
- **策略**：新增 `NativePolicy.max_continuations`（默认 2）。
- **工具**：新增 `todo`，默认未绑定。只有 Agent 显式绑定才可见（与其他内置工具的授权方式一致）。
- **持久化**：无迁移。`progress` 的 JSON 增加 `model_attempts` 字段，旧数据缺省为 0。

## 已确认的决定（待确认）

1. **截断续写**：实现，上限 2 次（可配置）。替代方案是保持现状（接受截断），推荐实现，因为路线图明确列出。
2. **最后一轮禁用工具**：实现，只在最后一个允许回合禁用工具。替代方案是禁用工具并不加提示，推荐加提示，避免模型只输出空内容。
3. **待办存储**：只存 Run 状态，不做会话持久化。替代方案是会话级持久化（需要迁移），推荐先做 Run 级，跨 Run 另行提案。
4. **模型尝试预算**：计数并新增预算字段，默认值不改变已发布 Agent 的行为。替代方案是只计数不限制，推荐同时提供上限，因为路线图的 3.15 要求四个维度分别计数并限制。

## 依赖

- 依赖 `2026-11-04-native-engine-split`（已完成）。
- 3.2 真实供应商验收仍未完成。本提案的测试使用假模型，不能替代真实供应商验收，需要你在设置页配好供应商后单独执行。

## 影响

- 代码：`packages/runtimes`（引擎、重试、判定）、`packages/core`（策略与预算字段）、`packages/tools`（待办工具）、`packages/platform`（Agent 发布的预算白名单，若存在）。
- 文档：路线图 3.7、3.10、3.15 按完成情况勾选；`packages/runtimes/docs/design.md` 同步。
