# 设计

聊天页作为标签宿主，独立纯展示组件接收 Run 事件与产物列表。轨迹按 Run 聚合 `eventsByRun` 与当前活跃 Run 的实时事件，并按 `sequence` 排序；其数据只读，不影响聊天状态。模型事件向后兼容历史记录：`model.started` 增加 `input_estimate_tokens`，`model.completed` 增加 `request_input_estimate_tokens` 与 `run_total_tokens`，既有 `tokens` 保持原语义。供应商 `usage` 作为单次模型调用实际用量展示；缺少 usage 时不伪造实际值。

实现参考 DeepSeek Harness `packages/client/ui-trajectory` 的事件账本、按步骤检视和用量检查器理念；Nexus 当前不持有该项目的完整模型输入日志，因此只呈现已持久化且授权可见的 Run 事件。
