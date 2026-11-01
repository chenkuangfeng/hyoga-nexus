# 全局活跃会话上限 `max_concurrent_sessions`

## 状态

已确认：用户要求继续实施，按推荐方案执行（提交时拒绝；默认 8；全部租户合计；以账本计数）。实施时的偏差见"实施说明"。

## 原因

同一会话的忙时排队已实现（FIFO，每会话上限 32）。但整个部署同时执行的会话数没有上限：每个会话的 Run 都会占用 worker 执行、模型连接与工具沙箱。架构文档 2.12 将其列为"另行提案"，本文件即该提案。

## 范围

- 配置项 `max_concurrent_sessions`（正整数）：同一时刻处于执行中（`started` 账本记录，或 Run 处于 running、waiting_input、waiting_approval）的会话数上限。
- 超限时新 Run 的处理方式见"需要确认的决定"。
- 不改变每会话排队规则：同一会话的第二个 Run 仍按 FIFO 排队，不占用新的会话名额。

## 需要确认的决定

1. **超限行为**（推荐：提交时拒绝）
   - 拒绝：提交返回 503，错误码 `session_capacity_exceeded`，不写入任何记录。
   - 或排队：Run 进入 `queued`，等待名额释放。
2. **默认值**（推荐：与 worker 数相同的小整数，例如 8；部署可改）。
3. **计数范围**（推荐：全部租户合计）。按租户分别计数需要另行设计公平性。
4. **状态来源**（推荐：以派发账本的 `started` 与 `unknown` 记录计数）。`unknown` 会话仍占名额，直到显式解除阻塞。

## 实施说明

- 占用名额的会话 = 持有 `queued`、`started` 或 `unknown` 记录的会话。草案只提到 started 与 unknown，但只在提交时检查时，仅统计执行中的会话无法保证上限：排队中的会话之后被领取会超出上限。因此排队中的会话也计入。
- 只有新会话的提交会检查上限；已持有名额的会话追加 Run 不检查。
- 配置：`configs/nexus.toml [platform].max_concurrent_sessions`，非正整数或非法值时拒绝启动相关请求（fail closed）。

## 影响

- 配置：`configs/nexus.toml` 新增可选项，缺省取推荐值。
- 数据库：无新表；查询账本的计数需要索引（`session_admissions(status)`）。
- API：提交接口新增 503 响应及错误码 `session_capacity_exceeded`。
