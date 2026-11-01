# 设计：上下文稳定化、工具结果治理与写入合并

## 一、现状与关键路径

一轮 Native 执行的数据流（代码位置以当前实现为准）：

1. `runs/preparation.py`：读取会话消息、摘要、进度，组装 `history`。
2. `NativeEngine.run`：压缩检查 → `append_context(history, working.anchor(turn))` → `collect_response` → 追加 assistant 消息 → `execute_batch` → 追加 tool 消息 → `save_progress`。
3. 每一步的持久化都经过 `DurableRuntimeStore`，每次调用开一个事务并校验租约。

输入 token 的组成为：`[system][工作记忆][摘要?][历史 1..N][当前 user]`，其中工作记忆每轮变化，位于历史之前。

## 二、P1：工作记忆位置

把 `append_context` 的插入位置从 `index 1` 改为消息列表末尾，作为独立的 user 消息。不选择"最后一条 user 之后"：那样会在 assistant 的 tool_calls 与其 tool 结果之间插入一条消息，违反 OpenAI 的工具调用配对格式。`working_memory_tail` 开关控制该行为，默认关闭直到评测通过。

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

## 十二、消息存储与回放规则（已确认）

本节为用户确认的三项决定的实施规格。整体遵循 Hermes Agent 的消息存储逻辑，并做三处调整：摘要独立成表；工具行的保存参考 WeKnora；跨 Run 不回放工具行。

### 12.1 术语

- **Run**：一次用户提问到最终回答的完整过程，对应 `runs` 表的一行。本节中的"轮次"一律指 Run，**不指**引擎循环里的一次模型调用（即代码中的 `progress.turns`）。

### 12.2 回放规则

| 消息 | 当前 Run 内 | 之前的 Run |
|---|---|---|
| user（用户提问、steer、ask_user 回答） | 回放 | 回放 |
| assistant 的最终回答（无 `tool_calls`） | 回放 | 回放 |
| assistant 的中间调用行（带 `tool_calls`） | 回放 | **不回放** |
| tool 结果行 | 回放 | **不回放** |
| 摘要（来自摘要表） | 作为前缀回放 | 作为前缀回放 |

只有 user 消息与 assistant 最终回答跨 Run 保留在模型视图中。

**Run 内回放必须完整**，因为以下场景需要 call 与 result 配对：
- 正常的多步工具调用，后一步依赖前一步的结果。
- `waiting_approval`、`waiting_input` 恢复时，引擎从数据库重新加载历史。
- 进程崩溃后，`resolve_incomplete_exchanges` 依赖 call 与 result 的配对补写占位。

### 12.3 工具行的存储

- **tool 行仍是唯一来源**，保存在 `messages` 表中（`role=tool`，`tool_call_id` 配对）。不另存一份 JSON 只用于界面展示，避免双份数据不一致。
- **界面展示**从 `messages` 与 `tool_invocations` 派生：按 Run 分组，assistant 的 `tool_calls` 与对应 tool 行合并为一个步骤。
- **不能用 `tool_invocations.output_summary` 替代完整结果**：它只保存 4000 字符摘要，无法支撑 Run 内恢复。
- 大输出（超过 P2 阈值）外置为 artifact，tool 行保存预览与句柄。这是 P2 在 Run 内仍然必要的原因。

### 12.4 跨 Run 的信息连续性

跨 Run 只保留最终回答，因此回答必须携带后续追问可能需要的事实。两项措施：

1. 系统提示要求最终回答保留关键数据（如文件路径、查询结果的数值），不只写"已完成"。
2. 需要跨 Run 持久的状态写入已有的 `session_checkpoints`（工作检查点），而不依赖工具行。

风险：若最终回答遗漏关键事实，追问时模型无法回答。这一点需要在评测样例中覆盖（见 12.7）。

### 12.5 摘要表（追加式）

摘要从 `context_summaries`（覆盖式，每会话一行）改为追加式表，建议结构：

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `session_id` | 所属会话 |
| `created_run_id` | 产生该摘要的 Run |
| `through_sequence` | 覆盖到的最大 `messages.sequence` |
| `content` | 摘要正文（标注为历史内容，非新指令） |
| `supersedes_id` | 被替代的上一条摘要，首条为空 |
| `created_at` | 创建时间 |

规则：
- 每次压缩**新增**一行，不修改旧行。当前有效摘要是该会话中 `through_sequence` 最大、且未被任何行 `supersedes_id` 指向的那一条。
- 压缩覆盖的 `messages` 行**不删除**，也不必打标记；视图组装时以 `through_sequence` 为界。
- 摘要的授权检查沿用现有逻辑：摘要覆盖的源 Run 必须对当前用户可见。
- 与 Hermes 的差异：Hermes 用 `compacted` 标记与会话 lineage 记录压缩链；我们用独立摘要表，查询更直接，压缩历史可追溯。

### 12.6 对其他优化项的影响

- **P2（工具结果外置）**的必要性下降：跨 Run 不回放后，长会话的工具输出不再随 Run 数累积。P2 只需解决**单个长 Run 内**的大输出，阈值可以更保守（或在基线后再定）。
- **P3（摘要压缩）**：摘要表结构改为追加式，P3 的"边界不每轮移动"规则仍然适用。
- **P8（准备阶段窗口化）**：跨 Run 过滤后，准备阶段只需读取：全部 user 与 assistant 最终回答（可分页，见 12.7），加上当前 Run 的全部行。
- **授权**：跨 Run 不回放 tool 行后，`_history_allowed` 对历史 Run 的检查只需覆盖 user 与 assistant 行，检查量减少。

### 12.7 实施与测试要求

- **准备阶段**：按 `run_id` 区分当前 Run 与历史 Run；历史 Run 只取 user 与最终 assistant 行。
- **引擎**：`append_context` 与历史组装不变，只改变输入的行集合。
- **测试**：
  - 同一 Run 内，工具多步调用后的上下文与改造前逐条一致。
  - 等待审批、等待输入、进程崩溃恢复后，当前 Run 的 call/result 配对完整。
  - 跨 Run 后，历史 tool 行不出现在模型输入中。
  - 摘要追加后，视图组装取到正确的有效摘要；旧摘要保留可查。
  - 评测：构造"追问依赖上一轮工具结果"的样例，比较改造前后的回答正确率；若下降，先补充最终回答的要求再决定是否上线。

### 12.8 与 Hermes / WeKnora 的差异汇总

| 项 | Hermes | WeKnora | 本方案 |
|---|---|---|---|
| 消息存储单位 | 每条消息一行 | user / assistant 每轮一行 | 每条消息一行（同 Hermes） |
| 工具步骤 | `tool_calls` JSON 列，tool 行 | `agent_steps` JSONB，仅展示 | tool 行为唯一来源，展示由其派生 |
| 跨轮回放 | 回放 active 行 | 只回放最终回答 | 只回放 user 与最终回答 |
| 压缩记录 | `compacted` 标记 + lineage | 检查点持久化 | 追加式摘要表 |

## 十三、不做的事

- 不引入新的缓存存储（Redis 等）。
- 不改变权限判断的时机（仍在每次工具调用时查库）。
- 不改变忙时排队、派发账本与快照的语义。
- 不把摘要或外置结果作为新的 system 指令；它们保持 `[untrusted historical content]` 的标注。
- 不另存工具步骤的 JSON 副本用于展示（见 12.3）。

## 十四、可配置项（智能体版本参数）

### 14.1 配置归属与生效规则

- 所有新参数都是**智能体的配置参数**，接入现有的 Native 设置机制：`NativePolicy`（行为，`budgets.behavior`）与 `ExecutionBudget`（预算，`budgets.budgets`），由 `runs/settings.py` 的 `defaults()` 与 `validate()` 统一定义默认值与校验。
- 个人默认值（`NativePreference`）只作用于之后创建的智能体版本，发布时快照进 `AgentVersion.budgets`。已有版本与已有会话不受影响，修改参数需要发布新版本。这与现有语义一致。
- 旧版本缺少新键时，读取时使用 dataclass 默认值。`view()` 当前直接返回已存储的设置，实施时需要与 `defaults()` 合并，否则旧记录缺键会导致表单显示不全。这一点列入实施任务。
- 每个参数都要在 `LABELS` 中登记中文名称，前端表单由 `defaults()` 自动生成，无需单独做界面。

### 14.2 参数清单

| 参数 | 归属 | 默认值 | 取值范围 | 含义 |
|---|---|---|---|---|
| `tool_output_inline_limit` | behavior | 2000 | 200–100000 | 工具输出超过该字符数即外置（P2）。 |
| `tool_preview_chars` | behavior | 500 | 0–`tool_output_inline_limit` | 外置后模型可见的预览长度。 |
| `tool_output_page_chars` | behavior | 4000 | 500–20000 | 分页读取工具单页返回的最大字符数。 |
| `tool_result_window_rounds` | behavior | 6 | 1–100 | 当前 Run 内，超过该模型调用次数的工具结果滚动裁剪为单行索引。 |
| `summarize_context` | behavior | `True`（已切换；评测结论待补） | 布尔 | 是否启用模型摘要压缩（P3）。 |
| `compact_high_ratio` | behavior | 1.0 | 0.5–1.0 | 历史字符数达到 `max_context_chars × 该比例` 时触发压缩。 |
| `compact_low_ratio` | behavior | 0.6 | 0.1–`compact_high_ratio` | 压缩后目标字符数占 `max_context_chars` 的比例。 |
| `summary_max_chars` | behavior | 8000 | 500–32000 | 单条摘要的最大字符数。 |
| `compaction_model_profile_version_id` | behavior | 空（使用智能体自身的模型） | 已发布的模型配置版本 | 压缩摘要使用的模型，便于用更便宜的模型做摘要。 |
| `max_context_chars` | budgets | 100000 | 已有 | 压缩与比例阈值的基准，沿用现有值。 |
| `max_output_tokens` | budgets | 2048 | 已有 | 沿用现有值。 |

模型本身（主模型）仍由智能体版本绑定的 `model_profile_version_id` 决定，本次不新增。

### 14.3 校验规则

- 所有数值参数只接受 `int` 或 `float`，越界拒绝，错误码沿用 `Native budget exceeds service limits` 风格。
- 跨字段约束：`tool_preview_chars ≤ tool_output_inline_limit`；`compact_low_ratio < compact_high_ratio`。
- `compaction_model_profile_version_id` 在发布时必须通过 `authorize_model` 检查，与主模型的授权规则一致；为空时使用主模型。
- 发布时写入快照前完成全部校验，不在运行时才发现非法配置。

### 14.4 与 P2 的关系

- P2 的阈值是 `tool_output_inline_limit`，默认 2000，**这是先给出的默认值，不是测量结论**。基线数据出来后按第一节的测量结果调整默认值，不改变参数本身。
- 预览与外置的规则：超过 `tool_output_inline_limit` 时，tool 行保存前 `tool_preview_chars` 个字符加句柄；完整内容落盘。
- 分页读取工具每次返回不超过 `tool_output_page_chars` 个字符，并且自身的输出不再外置（避免循环，见 12.6）。
