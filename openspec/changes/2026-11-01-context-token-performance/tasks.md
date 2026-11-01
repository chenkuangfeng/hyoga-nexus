# 实施任务

决定项已全部确认，可以开始实施。基线测量（第一节）不修改运行行为，应先做，用于确定 P2 阈值与各项的默认值。

## 确认

- [x] 确认 P1 工作记忆位置（消息列表末尾；实现细节见 design.md 第二节）。
- [x] 确认 P2 方向：超阈值输出外置，模型只拿预览与句柄，提供分页读取工具（读取工具不再外置）。具体阈值待基线确定。
- [x] 确认 P3：默认开启摘要压缩（`NativePolicy.summarize_context` 已改为 `True`，全量测试通过）。评测结论待补，见第六节。
- [x] 确认 P6 合并窗口（150ms / 256 字符），接受 SSE 粒度变化。
- [x] 确认 P9 并行白名单由工具定义显式声明，平台注册时校验。

- [x] 确认消息存储与回放规则：轮次指 Run；Run 内 tool 行保留为唯一来源；摘要表追加式（design.md 第十二节）。

## 一、基线（不改变行为）

- [ ] 构造固定会话集（至少 20 段，含工具调用、长输出、多轮）。
- [ ] 记录每轮输入 token、`cached_tokens`、模型耗时、数据库事务数、`run_events` 条数、准备阶段耗时。
- [ ] 结果写入 `baseline.md`，用于确定 P2 阈值与各项优先级。

## 二、低风险内部优化（不改变模型输入）

- [x] P4：每 Run 缓存工具定义（`runner.py`，恢复路径复用同一份）。执行时授权仍每次复核。测试：现有撤权用例（`test_revoked_grant_stops_new_submissions_even_with_cached_history`）通过；Run 中途撤权的专门用例见 `tests/test_native_hardening.py`（跨回合撤权：第二回合的调用不执行，Run 以 `run_authorization_denied` 结束）。
- [x] P5：`progress.tokens` 在供应商返回 usage 时直接使用（既有行为）；输入估算改为逐消息累加（`_message_bytes`），工具定义字符数每 Run 计算一次。
- [x] P8：历史授权结果在一次准备内按 Run 缓存（`_memo_allowed`）；摘要覆盖的行不再授权、不再物化，取消额外的覆盖行查询；`sequence` 加入投影行。测试：`tests/test_context_summary_cut.py`（覆盖行被替换、其余行保留；源 Run 不可见时摘要被忽略）。
- [x] P8 批量授权：准备阶段与 `model.started` 检查对会话内全部 Run 做一次批量判定（`histories_allowed`），同一资源授权在一次调用中只检查一次；每次准备仍实时读取授权，撤权即时生效。测试：`tests/test_history_batch_authorization.py`。Run 数仍决定读取的行数，行级读取优化不在本项内。

## 三、写入合并（改变 SSE 粒度）

- [x] P6：`message.delta` 按 150ms / 256 字符合并（`DeltaBuffer`，`NativePolicy.delta_flush_ms` / `delta_flush_chars`）。定时器在模型静默时也会刷出文本。测试：`tests/test_delta_batching.py`（合并后文本逐字相同、字符阈值、静默时定时刷出、窗口内取消仍生效）。
- [x] P7：仅合并两组相邻写入：`model.completed` 与 assistant 消息；`turn.completed` 与 `save_progress`（`DurableRuntimeStore.commit`，同一事务与一次租约校验）。工具执行之间的写入不合并。测试：worker 端到端用例确认一条 assistant 消息与事件顺序。事务失败整组回滚的用例见 `tests/test_native_hardening.py`（组内消息写入失败时，同组事件与消息整体回滚）。

## 四、上下文稳定化（改变模型输入，需要评测）

- [ ] P1：`working_memory_tail` 开关，默认关闭。在 `evals/` 中建立对比样例。
- [x] P3：摘要落库、滞后阈值（`compact_high_ratio` / `compact_low_ratio`）、降级不落库；摘要长度受 `summary_max_chars` 限制；`compaction_model_profile_version_id` 指定的压缩模型每次调用授权，不可用时降级。测试：`tests/test_compaction_policy.py`（阈值之间不压缩、超过高阈值压缩到低目标以下、摘要截断、降级事件、压缩模型使用与释放）。评测（P3 的质量对比）待补。
- [x] P2：工具输出外置与滚动裁剪；`read_tool_output` 分页读取工具。测试：外置内容的授权与审计；视图确定性。（阈值待基线确定后再调整默认值。）

## 四之一、配置接入（design.md 第十四节）

- [x] 在 `NativePolicy` 增加 `tool_output_inline_limit`、`tool_preview_chars`、`tool_output_page_chars`、`tool_result_window_rounds`、`compact_high_ratio`、`compact_low_ratio`、`summary_max_chars`、`compaction_model_profile_version_id`、`working_memory_tail`，默认值见规格。
- [x] `runs/settings.py`：`LABELS` 登记中文名；`validate()` 经 `NativePolicy` 做范围与跨字段校验；保存时 `authorize_model` 检查压缩模型。
- [x] `view()` 与旧记录合并 `defaults()`（`_with_defaults`），保证旧设置缺键时表单完整。
- [x] 发布时（`agents/service.py` 的 `publish_agent`）重新校验 Native 行为参数，并检查压缩模型授权。
- [x] 测试：`tests/test_context_policy_config.py`（默认值、非法取值、旧记录补齐、标签完整）。发布路径的拒绝用例待补（见下）。
- [x] 测试：发布时非法行为参数与无权限压缩模型的拒绝路径，`tests/test_publish_native_validation.py`（带数据库）。
- [ ] 基线完成后，依据测量结果调整 `tool_output_inline_limit` 默认值，并记录依据。

## 四之二、消息存储与回放（P10、P11，已确认）

- [x] P10：准备阶段对历史 Run 跳过 tool 行与带 `tool_calls` 的 assistant 行；当前 Run 的全部行保留。测试：`tests/test_run_scoped_replay.py`（当前 Run 内完整可见，后续 Run 不回放工具结果、保留最终回答）；`test_multitool_bad_arguments_hooks_and_session_history` 的断言已按新规则更新。
- [x] P10 等待与恢复：当前 Run 的 call/result 配对保持完整（同一 Run 内回放不变，既有等待与恢复用例通过）。
- [x] P10 跨 Run 持久状态：工作检查点写入 `session_checkpoints`（既有 `update_working_checkpoint`），准备阶段读取，不依赖工具行。
- [ ] P10 系统提示要求保留关键事实：按设计为条件项，仅在下方评测显示正确率下降时加入；未加入，因为它会改变所有 Run 的模型输入。
- [x] P11：迁移 `context_summaries` 为追加式（迁移 `b2f6a1d8c3e5`，`supersedes_id`、`id` 主键、`created_at`）。旧数据迁入为第一版本，降级只保留有效摘要。测试：`tests/test_summary_chain.py`（链式追加、旧行保留、不前移的摘要不写入、迁移升降级）。
- [ ] 评测：构造"追问依赖上一轮工具结果"的样例，比较改造前后正确率；下降则先补充回答要求，再决定上线。（需要真实模型，未执行。）
- [x] 界面展示从 `messages` 与 `tool_invocations` 派生，不另存 JSON 副本（未新增存储，符合规格）。

## 五、并行只读工具

- [x] P9：工具定义显式声明；注册时校验只读工具无副作用；白名单内并行，结果顺序不变。
- [x] 测试：并行执行时结果顺序与模型声明顺序一致；非白名单工具保持串行（`tests/test_native_hardening.py`）。

## 六、默认值切换与验证

- [ ] 对照基线，逐项记录收益（token、事务数、耗时）与质量结果。
- [ ] 仅对通过验证的项修改 `NativePolicy` 默认值，并在本文件中记录依据。
- [ ] 评测结论写入 `evals/` 对应目录的报告。

## 七、文档与归档

- [x] 同步更新 `docs/architecture.md` 2.2（上下文、压缩）与 2.12（事件与持久化）。
- [x] 路线图第 3 步新增性能验收项（3.21，未完成）。
- [ ] 归档本变更（仅在全部已确认项完成且验证通过后）。
