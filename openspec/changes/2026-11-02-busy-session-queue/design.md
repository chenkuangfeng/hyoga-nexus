# 设计

## 提交

1. 在提交事务中照常插入 Run 与 Outbox 记录，并追加 FIFO 条目（已实现）。
2. 若会话已有非终态 Run，不再返回 409，而是返回 202；`queue_position` 为该 Run 在 FIFO 中前面 `queued` 条目的数量加一。
3. 若会话的 `queued` 条目已达 32，在插入前拒绝，返回 409 `session_queue_full`，不写入任何记录。
4. 幂等键重放照旧，返回原结果，不重新计算队列位置。

## 派发

- Outbox 仍按 Run 派发。worker 领取后调用 `select_head`：
  - 队首是本 Run：`cas_claim`，执行。
  - 队首不是本 Run，或会话 `started`/`unknown` 阻塞：不写失败，释放 Outbox 租约，`available_at = now + 2s`。
  - 账本与 Run 不一致（队首为空但 Run 为 queued）：沿用现有错误路径，报错并由租约回收。
- 退避期间其他会话的 Run 不受影响。

## 取消

- 排队中的 Run 被取消：Run 变为 `cancelled`，终态钩子释放 FIFO 条目，队列中后续条目前移。
- 运行中的 Run 取消：沿用现有取消流程。

## 测试要点

- 忙时提交返回 202 与正确的 `queue_position`；第 32 条成功，第 33 条返回 `session_queue_full` 且无记录写入。
- 幂等重放返回原结果。
- 非队首领取后租约释放，Run 仍为 `queued`，无失败事件。
- 队首终态后，下一条被领取并执行，顺序与提交顺序一致。
- 取消排队中的 Run 后，后续条目可执行。
- 多会话互不影响：会话 A 排队不阻塞会话 B。
- 崩溃后 `unknown` 阻塞：提交仍返回 409（unresolved run），不进入排队。
