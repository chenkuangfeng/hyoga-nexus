# 任务：Native 引擎行为补齐

> 状态：草稿，待确认 proposal.md 第 6 节的四项决定。

## 1. 前置（确认后执行）

- [ ] 1.1 确认 proposal.md 第 6 节的四项决定。
- [ ] 1.2 核实 3.14 恢复校验：快照版本、会话与主体、Agent 与模型版本、资源授权、审批消费状态、已完成调用。逐项记录"已有/缺失"，缺失项另开提案。
- [ ] 1.3 核实 Agent 发布接口对预算字段的校验（白名单位置），确定 `max_model_attempts` 的接入点。

## 2. 截断续写（3.7）

- [ ] 2.1 `NativePolicy.max_continuations`（默认 2）及校验。
- [ ] 2.2 `CompletionJudge` 在截断且未超上限时返回续写决定（新枚举值）；超上限时保持 `ACCEPT_TRUNCATED`。
- [ ] 2.3 编排器追加续写提示并发出 `answer.continued`。
- [ ] 2.4 测试：续写一次后完成；超过上限后接受截断并发出 `answer.truncated`；续写不计入工具错误预算。

## 3. 最后一轮禁用工具（3.7）

- [ ] 3.1 编排器在 `progress.turns == budget.max_rounds` 的回合传入空工具定义，并追加提示。
- [ ] 3.2 发出 `turn.tools_disabled`。
- [ ] 3.3 测试：最后一轮模型请求中工具定义为空；之前的回合不变；基线场景不受影响。

## 4. 待办工具（3.10）

- [ ] 4.1 `packages/tools/src/nexus_tools/builtins/todo.py`：`list`、`set` 两种操作，参数校验，结果为模型可读文本。
- [ ] 4.2 状态存于 `progress.state['todos']`，随 Run 结束释放。
- [ ] 4.3 注册到内置工具清单，默认不绑定。
- [ ] 4.4 测试：列表与替换、非法操作码拒绝、未绑定时不可见、跨 Run 不可见。

## 5. 模型尝试计数（3.15）

- [ ] 5.1 `RetryModel` 每次实际请求通过回调计数，写入 `progress.model_attempts`。
- [ ] 5.2 `ExecutionBudget.max_model_attempts`，默认 `max_rounds * (model_retries + 1)`；超出时 `RuntimeFault('budget_exhausted')`。
- [ ] 5.3 `model.attempt` 事件，只含序号与回合，不含请求内容。
- [ ] 5.4 测试：重试次数计入；上限触发显式失败；旧 progress（缺少字段）读取为 0。

## 6. 核实与文档

- [ ] 6.1 将 1.2 的核实结果记入本文件与路线图 3.14 的说明。
- [ ] 6.2 `packages/runtimes/docs/design.md` 与 `packages/core` 的预算说明同步。
- [ ] 6.3 路线图 3.7、3.10、3.15 按完成情况勾选；3.13 与 3.14 只在核实后勾选，未完成的注明原因。
- [ ] 6.4 全量后端测试通过；`test_native_engine_golden.py` 基线保持一致。
