# 设计

`DurableRuntimeStore.checkpoint` 在更新 `session_checkpoints` 前锁定对应 Session 行，读取当前 Run 最新一条持久化消息，并通过既有 `append_summary` 追加会话摘要。摘要链使用现有 `through_sequence` 与 `supersedes_id`；不新增表或迁移。摘要内容标记为来源记录的参考资料，不能作为新指令。工具成功后，dispatcher 通知 Native 主循环；主循环立即将当前消息列表折叠为 system 前缀、检查点摘要及当前 assistant 工具调用和完整结果交换，并清空已被检查点替代的 Run 内工作记忆摘录。

若当前 Run 尚无持久化消息，仍保存工作检查点，但不建立摘要切点。并发或较旧切点由 `append_summary` 拒绝前移。`ExecutionPreparer` 继续按现有授权规则验证摘要来源，复用最新有效摘要并跳过其覆盖消息。若有效摘要正是由该检查点写入，则复用现有工作检查点注入位置，不再把摘要重复加入历史消息。

这借鉴本地 WeKnora 的消息边界检查点，以及 Hermes 在会话活动上下文中用压缩结果延续后续模型请求的做法；沿用 Nexus 的原始消息保留、追加式摘要链和来源 Run 授权检查。运行时事务只做数据库工作，不增加模型调用。
