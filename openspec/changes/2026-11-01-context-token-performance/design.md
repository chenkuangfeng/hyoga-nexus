# 设计：上下文稳定化、工具结果治理与写入合并

## 一、现状与关键路径

一轮 Native 执行的数据流（代码位置以当前实现为准）：

1. `runs/preparation.py`：读取会话消息、摘要、进度，组装 `history`。
2. `NativeEngine.run`：压缩检查 → `append_context(history, working.anchor(turn))` → `collect_response` → 追加 assistant 消息 → `execute_batch` → 追加 tool 消息 → `save_progress`。
3. 每一步的持久化都经过 `DurableRuntimeStore`，每次调用开一个事务并校验租约。

输入 token 的组成为：`[system][工作记忆][摘要?][历史 1..N][当前 user]`，其中工作记忆每轮变化，位于历史之前。

## 二、P1：工作记忆位置

把 `append_context` 的插入位置从 `index 1` 改为"最后一条 user 消息之后"（若最后一条是 tool 结果，则追加在其后且作为独立 user 消息）。

- 不改变内容，只改变位置。
- 稳定前缀：`[system][tools][历史 1..N]` 在相邻两轮之间保持字节一致，供应商可以命中缓存。
- 风险：模型对"尾部插入的 user 消息"可能更敏感。需要用评测样例对比。

## 三、P2：工具结果外置与滚动裁剪

- 工具输出超过 `tool_output_inline_limit`（待基线确定，初值 2000 字符）时，完整内容写入 artifact，历史中的 tool 消息仅保留前 N 字符加句柄，例如 `[artifact:<id>, 12.3KB, 截断]`。
- 模型需要完整内容时，通过读取 artifact 的工具获取（这是新工具，需要走授权与审计）。
- 滚动裁剪：超过 `tool_result_window`（例如最近 6 轮）的 tool 结果，在组装视图时替换为单行索引（工具名、状态、句柄）。源消息不改，仅影响模型视图。这与 `compact_history` 的"摘录"一样只在视图层生效，因此视图需要是确定性的，且边界变化不能太频繁（见 P3）。

## 四、P3：摘要压缩与滞后

当前 `compact()`（`context/compaction.py`）在每轮超限时都可能调用模型，且 `compact_history` 每个 Run 重算。

变更：

- 启用 `summarize_context` 默认值，摘要通过 `save_summary` 落库到 `context_summaries`。
- 滞后：触发阈值 `T_high`（默认 100% of `max_context_chars`），压缩目标 `T_low`（默认 60%）。压缩一次后，直到输入再次超过 `T_high` 之前，边界保持不变，摘要文本不变。
- 摘要只覆盖 `through_sequence` 之前的消息。新摘要生成时，输入为"旧摘要 + 新增旧消息"，而不是重新读取全部历史。
- 摘要失败时降级为确定性摘录（已有行为），且降级结果不落库，下一次超限时重试摘要。

这样，相邻轮次的前缀在大多数时候保持不变，缓存命中率由"每轮变化"变为"每 K 轮变化一次"。

## 五、P4：Run 内缓存工具定义

`gateway.definitions()` 在 `NativeEngine.run` 的每轮循环中调用。变更为：

- 在 Run 开始时调用一次，结果保存在执行对象中（执行对象本身每 Run 新建，符合现有模型）。
- 执行时的 `access.authorize` 不变，仍在每次工具调用时查库，撤权在下一次调用时生效。
- 风险：Run 中途撤销工具绑定时，`definitions` 仍会包含该工具直到 Run 结束。但执行时授权会拒绝调用，因此不会产生越权。需要在文档中明确这一语义。

## 六、P5：token 估算校准

- 每轮结束后，用 `response.tokens`（来自供应商 usage）更新 `progress.tokens`，替代 `input_estimate + output` 的估算。
- 轮内预算检查仍使用估算，但用上一轮的 `input_tokens / chars` 比例做校准系数。
- `input_estimate` 改为按消息逐条累加字符数，不再对整段历史做 `str()`。

## 七、P6、P7：写入合并

**delta 合并**：`collect_response` 不再对每个文本块调用 `store.emit`。改为在内存中累积，满足以下任一条件时 flush 一条 `message.delta`：距上次 flush 超过 150ms、累积字符超过 256、流结束。

- 最终的 assistant 消息仍然完整写入 `messages`，不受影响。
- 断线续传依赖 `run_events` 中的 `sequence`，合并后序号变少但仍单调递增。

**一轮内合并**：引入 `TurnWriter`（或在 store 中提供 `batch()` 上下文），一轮内的 `emit`、`save_progress`、`message` 共用一个事务和一次 `_run` 校验。在一轮结束时统一提交。

- 注意：取消与超时检查必须仍然在每个 await 点进行，不能因为合并而延迟到轮末。取消信号本身不写库，检查只读内存标志。
- 事务失败时整轮回滚，行为与现在一致（`interrupted` 或 `unknown`）。需要验证回滚后的进度与消息是否一致。

## 八、P8：准备阶段窗口化与授权缓存

- 读取会话消息时只取最近 `N` 条（默认 200）加上摘要覆盖之外的部分；更早的消息由摘要替代，不再全部读入内存。
- `allowed_runs` 与 `_history_allowed` 结果在一次准备中按 `run_id` 缓存；同一资源只授权一次。
- `source_run_id` 的检查改为批量查询：先收集所有需要的 `run_id`，一次 `IN` 查询取回，而不是逐条 `db.get`。
- 授权语义不变：每个历史来源仍然要通过当前用户的授权，只是查询次数减少。

## 九、P9：并行只读工具

- 在工具定义中显式声明 `read_only`、`idempotent`、`side_effects`（已有字段），由平台在注册时校验：声明为只读的工具不得在 `side_effects` 中为真。
- `parallel_reads` 默认开启，但只对满足条件的工具并行；其余工具保持串行。
- 并行执行时，结果仍按模型声明顺序写入 tool 消息（已有行为）。

## 十、验证方案

1. **基线**（先于任何改动）：
   - 固定一组会话（至少 20 段，含工具调用、长输出、多轮）。
   - 记录每轮的输入 token、`cached_tokens`、模型耗时、数据库事务数、`run_events` 条数、准备阶段耗时。
   - 基线数据写入本目录 `baseline.md`。
2. **分项验证**：P1–P9 每项单独开关，单独测量，避免混在一起无法归因。
3. **质量回归**：在 `evals/` 中为 P1、P2、P3 建立对比样例，判断标准为任务完成与事实一致性，不以 token 数为唯一指标。
4. **正确性测试**：
   - P6：delta 合并后的文本与未合并时逐字相同；取消在合并窗口内仍然及时生效。
   - P7：轮内事务失败后，消息与进度回到上一轮结束的状态。
   - P8：窗口化后，摘要覆盖的消息仍可在审计中追溯；撤权后历史不再可见。
   - P4：Run 中途撤权后，调用被拒绝。

## 十一、开关与默认值

所有变更通过 `NativePolicy` 控制，每项独立字段：

| 字段 | 初始默认值 | 验证后默认值 |
|---|---|---|
| `working_memory_tail` | `False` | `True` |
| `tool_output_inline_limit` | `None`（关闭） | 待基线 |
| `summarize_context` | `False` | `True` |
| `delta_flush_ms` | `0`（每块写入） | `150` |
| `parallel_reads` | `False` | `True` |

默认值只在对应的验证项通过后修改，并在 tasks.md 中记录依据。

## 十二、不做的事

- 不引入新的缓存存储（Redis 等）。
- 不改变权限判断的时机（仍在每次工具调用时查库）。
- 不改变忙时排队、派发账本与快照的语义。
- 不把摘要或外置结果作为新的 system 指令；它们保持 `[untrusted historical content]` 的标注。
