# 模型错误与终态一致性

## Why

当前 Nexus 三协议适配器的错误、终态和用量语义不一致。已本地复现 Responses 非流式 failed 被归为 done/stop、Anthropic 未闭合工具仍被返回、Responses cached 输入被重复计入总量。普通正常路径回归通过不能排除这些缺陷；将永久拒绝归为 provider_unavailable 还可能引发重试。

参考来源为 GenericAgent `a9a36b4` 与 WeKnora `e1f9a6166` 的模型协议和重试实现。本提案是完整迁移的一个独立验收批次，不表示完整对齐。

## What Changes

- 三协议统一失败/缺终态/截断/过滤映射，失败不返回正常 done；保留已流出的文本，禁止执行未完整确认的工具。
- 区分永久 HTTP 拒绝与暂时故障，保留既有错误码并补稳定分类；重试/切换只发生在允许且尚无输出的请求。
- 修正协议级 input/output/cache/total 计算和累计 usage 合并。
- 覆盖无 item ID/稀疏工具索引等已核实兼容路径，缺失或歧义数据显式失败。
- 同步模块文档、来源归属、行为测试和验证记录。

## Capabilities

### New Capabilities

- `model-terminal-consistency`：三协议模型结果归一、工具完整性门禁及有界错误恢复。

### Modified Capabilities

无已发布规格修改；本批补充仍在实施中的 Native 能力，不归档完整 Native 迁移提案。

## Impact

影响 runtimes/native/models 的协议、错误、usage、retry/routing 边界，以及必要的 Native 结果消费门禁和测试。core 仅在确需携带内部有界重试信息时扩展兼容字段，不外泄 SDK 类型。无数据库迁移、无新用户配置、无新依赖、无界面交互变化；已有重试/预算设置与版本快照继续生效。

不在本批：完整 thinking/signature 持久化与重放、全部厂商参数/端点语法、多模态、长期记忆、沙箱/六项执行工具，以及真实模型/PostgreSQL 验收。这些继续跟踪，不视为删除或已对齐。

## 需要确认的行为决策

1. 保持 Nexus 输出后不重发本次请求；替代 GA 部分流后仍可能重发的行为，保留部分文本并显式失败。
2. Chat 保持 Nexus 必须有有效 finish_reason；WK 的 DONE-only 宽松例外不照搬。Responses 必须收到 completed/incomplete；Anthropic 有有效 stop_reason 且全部工具块闭合可结束，不额外要求 message_stop，以兼容 WK。
3. 截断/过滤/不完整优先于工具调用，避免 WK Responses 工具优先级掩盖截断。截断纯文本继续既有 answer.truncated 行为；截断工具不执行。
4. 对永久拒绝不重试；仅选定暂时 HTTP 状态与网络故障可在预输出阶段重试，区别于 WK JSON helper 全部 HTTP 不重试和 GA 更宽集合。

## Status

用户已明确确认，局部实现与本地验收已完成并归档；环境边界见 [verification.md](verification.md)。实施与验收清单见 [tasks.md](tasks.md)，具体映射见 [design.md](design.md)。
