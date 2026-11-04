# 任务：Native 引擎行为补齐

> 状态：已实施并通过测试（后端全量 660 通过、1 跳过）。1.2 的核实结果见下；3.13、3.14 的未完成项已写入路线图。

## 1. 前置

- [x] 1.1 确认 proposal.md 第 6 节的四项决定（已确认，推荐方案）。
- [x] 1.2 核实 3.14 恢复校验。结果：
  - 已有：审批请求只能消费一次（重复消费返回冲突）；审批绑定运行配置哈希，配置变化后拒绝（`platform/runs/approvals.py`）；恢复审批时校验租户与运行所有者；待处理调用之外的已完成调用不重放（`engine/recovery.py`）；每次工具调用由网关重新授权；历史投影时复核资源授权（`platform/runs/messages.py`）。
  - 缺失：运行进度（progress）没有格式版本标记，恢复时无法拒绝未知版本。另行提案。
- [x] 1.3 预算白名单：worker 按 `ExecutionBudget` 字段读取，设置页表单由后端 schema 生成，新增字段需要 `LABELS` 条目（已补）。发布接口校验复用 `ExecutionBudget`，新字段由其校验。

## 2. 截断续写（3.7）

- [x] 2.1 `NativePolicy.max_continuations`（默认 2，范围 0–5）。
- [x] 2.2 `CompletionJudge` 返回 `CONTINUE_TRUNCATED`；超上限时 `ACCEPT_TRUNCATED`。
- [x] 2.3 编排器追加续写提示并发出 `answer.continued`。
- [x] 2.4 测试：续写后完成、超上限接受截断、完整响应清零计数、0 次时保持旧行为（`tests/test_native_engine_components.py`、`tests/test_native_behaviour.py`）。

## 3. 最后一轮禁用工具（3.7）

- [x] 3.1 最后一个允许回合传入空工具定义，并追加提示。
- [x] 3.2 发出 `turn.tools_disabled`。
  - 说明：模型仍返回的工具调用不执行，记为"Not executed"（超出草稿，属于安全约束）。
- [x] 3.3 测试：最后一轮无工具且有提示；之前的回合不变；最后一轮的调用被拒绝执行。

## 4. 待办工具（3.10）

- [x] 4.1 `packages/tools/src/nexus_tools/builtins/todo.py`：`list`、`set`（整体替换，最多 50 项），schema 由网关校验。
- [x] 4.2 状态存于 `progress.state['todos']`。为此新增 `RunServices`，worker 装配时传入 `progress.state`（与进度为同一对象）。
  - 说明：`RunServices` 把其余属性透传给存储，已有内置工具不需要修改。
- [x] 4.3 注册到内置工具清单，默认不绑定（`BUILTIN_TOOL_NAMES`）。
- [x] 4.4 测试：设置后读回、空列表、缺少 items 拒绝、无 Run 状态时拒绝。跨 Run 隔离由状态存于 progress 保证。

## 5. 模型尝试计数（3.15）

- [x] 5.1 `RetryModel` 在每次真实请求前调用 `begin_attempt`；编排器绑定 `AttemptCounter`，计数写入 `progress.model_attempts`。
- [x] 5.2 `ExecutionBudget.max_model_attempts`（0 为推导值）；超出时 `budget_exhausted`，请求不发送。
- [x] 5.3 `model.attempt` 事件，只含序号与回合。
- [x] 5.4 测试：重试计入、上限前拒绝发送、旧进度行读取为 0、负值拒绝。

## 6. 核实与文档

- [x] 6.1 1.2 的核实结果已记入本文件与路线图 3.14。
- [x] 6.2 `packages/runtimes/docs/design.md` 已更新。
- [x] 6.3 路线图 3.7、3.10、3.15 勾选；3.13、3.14 未勾选并注明原因。
- [x] 6.4 全量后端测试通过；`test_native_engine_golden.py` 基线保持一致。
