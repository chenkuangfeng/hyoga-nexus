# 设计（单机版 Hermes 式网关）

## 一、进程模型

```text
单个网关进程
├── 入口：HTTP API、渠道适配器（后续）
├── 会话调度器：每会话 FIFO，忙时策略，全局活跃会话上限
├── 会话对象缓存：session_id → SessionObject（有界，LRU，空闲 TTL）
│     ├── 会话数据：历史投影、检查点、绑定、记忆快照引用
│     └── 执行对象：Run 执行器（可重建，恢复不依赖它）
└── 账本（SQLite，单文件，BEGIN IMMEDIATE 写入）
      ├── runtime_epoch：每次进程启动 +1
      ├── session_admissions：queued / started / unknown / terminal
      └── executions：执行记录，带 owner_epoch
```

事实源：单机版的会话事件与账本都在 SQLite。进程内缓存只是副本。

## 二、会话对象缓存

- 键：`session_id`。值：会话数据 + 可选执行对象。
- 写入：先写 SQLite（带当前 epoch），提交成功后更新缓存。
- 读取：缓存命中则不读库；未命中则从 SQLite 全量装配一次。
- 不缓存：权限判断、凭据明文、超阈值工具输出原文（只存句柄）。
- 回收：LRU 超过 `max_sessions`；空闲超过 `idle_ttl`；单对象字节超限时只保留检查点与最近消息。
- 进程内没有其他写者，因此不需要修订号或所有权校验。

## 三、会话调度（参考 Hermes）

- 忙时策略（每会话）：默认 `interrupt`；`queue` 排队；`steer` 注入。打断时若有子任务或压缩进行中，降级为 `queue`。
- 每会话待处理队列上限 32，超限丢弃并记录。
- 全局 `max_concurrent_sessions`，超限拒绝新会话（返回提示，不排队）。
- 同一会话的 Run 串行。

## 四、账本与 CAS 领取

- 入队：写入 `session_admissions`（`queued`）。
- 领取：`UPDATE session_admissions SET status='started', owner_epoch=:e, generation=:g WHERE id=:id AND status='queued'`，rowcount 必须为 1。
- 取队首：`ORDER BY seq LIMIT 1`。
- 阻塞：会话有 `started` 或 `unknown` 记录时不领取。
- 结束：`terminal`，写入结果。

## 五、启动恢复

1. `runtime_epoch` +1。
2. 所有 `owner_epoch < 当前 epoch` 的 `started` 与执行记录改为 `unknown`。
3. 对应会话进入阻塞态（`unknown_execution`），不自动重放。
4. 显式解除（用户确认或运维命令）后，会话恢复为可领取，并记录审计事件。

这与架构 2.12 的"中断不重放"一致，只是把"中断"具体化为 `unknown` 状态。

## 六、与当前代码的差异（确认后再改）

- `apps/worker` 的单机入口与 `execute_native` 的每 Run 构建模式会被替代。
- `packages/platform` 的 Outbox 与 lease 逻辑保留给多租户 PG 实现；单机版使用 SQLite 账本。
- 架构 2.2 的恢复规则（不依赖进程内锁、回调、SDK 句柄）仍然适用。

## 七、测试要点

- 账本：CAS 领取只有一方成功；队首顺序；`queue_full` 与 `max_concurrent_sessions` 拒绝路径。
- 缓存：命中时 Run 期间零会话数据读库（查询计数）；LRU 与 TTL 回收后从库重建结果一致。
- 恢复：模拟进程崩溃重启，旧 epoch 的 started 变为 `unknown`，会话阻塞，不重放。
- 权限：撤销权限后，同会话下一次工具调用被拒绝。
- 关停：停止接收新 Run，未完成的标记为 `unknown`。
