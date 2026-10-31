# 实施任务

待用户确认 proposal.md 的"影响与待确认"五项后才开始。

## 确认

- [ ] 用户确认单进程部署、执行对象缓存、多租户保留 worker、架构文档修改时机、单机事实源为 SQLite。

## 账本（路线图第 2 步，单机实现）

- [ ] SQLite 账本：`runtime_epoch`、`session_admissions`（queued / started / unknown / terminal）、执行记录，写入统一使用 `BEGIN IMMEDIATE`。
- [ ] CAS 领取与取队首（`ORDER BY seq`）；rowcount 检查。
- [ ] 每次写入带 `owner_epoch`；过期 epoch 返回 `stale_epoch`。
- [ ] 启动恢复：旧 epoch 的 started 与执行记录改为 `unknown`，会话阻塞；显式解除与审计。
- [ ] 测试：并发领取、队首顺序、`stale_epoch`、崩溃恢复、显式解除。

## 网关与调度（路线图第 3 步）

- [ ] 单进程网关：API 与 Run 执行同进程；关停时停止接收并标记未完成为 `unknown`。
- [ ] 会话对象缓存：有界、LRU、空闲 TTL、单对象字节上限；不缓存权限。
- [ ] 会话内串行；忙时策略 interrupt（默认）、queue、steer；打断降级规则。
- [ ] 队列上限 32；`max_concurrent_sessions` 拒绝路径。
- [ ] 测试：缓存命中时 Run 期间零会话数据读库；权限撤销即时生效；忙时策略；容量淘汰。

## 文档与归档

- [ ] 同步更新架构文档 1.2、2.2、2.12 与路线图第 2、3 步，并说明单机与多租户的差异。
- [ ] 归档本变更。
