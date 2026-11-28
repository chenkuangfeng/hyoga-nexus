# 设计：Run 累计 Token 预算

## 决策

`ExecutionBudget.max_tokens` 继续表示 Run 内累计用量上限，但 0 表示未配置上限。默认值设为 0；`RuntimeProgress.tokens` 始终累计实际用量或估算用量，用于审计和诊断，不再默认作为停止条件。

Native 每次请求继续受 `max_output_tokens` 限制；上下文历史继续由 `max_context_chars` 和压缩策略整理。保留已配置的正值累计预算兼容既有调用方。子 Run 在父预算为 0 时继承无累计上限，否则仍在父剩余额度内分配。

## 压缩比较及消息流

- **WeKnora**：Agent Engine 的消息列表在一个执行循环中持续更新；超出上下文窗口减输出预留的绝对阈值后，旧前缀总结成摘要，最近 `KeepRecentTokens` 保持原文。压缩结果替代当前 Engine 后续轮次使用的消息视图，检查点保存可覆盖的已存轮次摘要。摘要模型失败时用有界原文档案降级。压缩后仍超阈值则先裁剪工具结果；若供应商确认上下文溢出，当前执行最多强制压缩并重试一次，第二次仍溢出就返回错误。无可压缩内容或压缩收益不足时会在相同消息长度上抑制重复摘要调用。参见 `opensource/agents/WeKnora/internal/agent/observe.go`、`engine.go` 与 `internal/agent/compaction/`。
- **Hermes**：会话压缩器在会话 agent loop 的模型请求路径上维护活动消息历史；达到模型窗口比例阈值后把较旧上下文汇总并与近期消息合并，后续模型轮次使用改写后的活动历史。收到真实 provider usage 后判断压缩是否已把输入降至阈值以下；两次连续无效压缩会触发反抖退避，并在约 5 分钟后允许一次探测恢复。摘要本身失败则尝试不同模型/降级路径或保持上下文并报告失败，不会把仍超阈值的列表无限循环压缩。具体持久化形态由会话后端决定。参见 `opensource/agents/hermes-agent/agent/context_compressor.py`。
- **本仓库**：`context_summaries` 是会话级追加摘要链，包含覆盖序号和来源 Run；新 Run 在检查来源 Run 授权后，从有效摘要接续，并跳过摘要覆盖的原始消息。每会话写摘要时锁定 Session 行，链只向前推进。原始消息、工具调用记录和 Run 事件保留；工具结果窗口只裁剪模型请求视图。摘要失败退回确定性摘录。供应商报告上下文溢出时强制压缩到更低目标、缩短旧工具结果窗口并重拟合，最多重试一次；仍超限则 `model_context_exceeded`。各 Run 的 `RuntimeProgress.tokens` 累计用量，但默认不再终止 Run。

## 失败与边界

- 仍受 `max_rounds`、`max_seconds`、`max_errors` 和派生/显式模型请求次数限制。
- 明确设置正值 `max_tokens` 时保留原硬上限行为。
- 本仓库当前尚未把所有模型的真实 Context Window 统一纳入 Runtime 契约；`max_context_chars` 是字符预算，不声称等同于 Token 窗口。供应商仍可拒绝超窗请求，该类问题使用既有错误恢复/终态处理。
- 供应商上下文溢出恢复最多一次；压缩不能删除当前用户请求或最新完整工具交换，若剩余固定提示、工具 schema 或当前交互仍过大，Run 显式失败，不做无限缩减或重试。
- 一次 Run 的累计 Token 统计包含调用累计，而模型请求上下文是每次调用的活动消息视图；同一前缀可能在同一 Run 的多个模型调用中重复发送并计量。
