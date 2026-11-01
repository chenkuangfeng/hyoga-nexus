# 实施任务

待用户确认 proposal.md 的"需要确认的决定"四项后才开始。

## 确认

- [x] 确认单机版进程模型（单进程网关或 API 与 worker 分离）。
- [x] 确认崩溃恢复策略（`unknown` 阻塞，或 `error` 允许重试）。
- [x] 确认会话头读取可以接受。
- [x] 确认架构文档与路线图的修改时机。

## 快照与账本（路线图第 2 步）

- [x] 迁移：会话水位（`sessions.watermark`）、快照版本、快照存储（`sessions.snapshot`、`snapshot_version`）。账本的 `owner_epoch` 与 `unknown` 状态已由既有迁移提供。（SQLite 往返已验证；PostgreSQL 随 2.9。）
- [x] 快照版本化：v2 JSON，未知版本拒绝。v1 迁移注册表为空：仓库中从未持久化过 v1 数据，没有需要迁移的旧格式，因此暂不编写迁移函数。
- [x] 乐观并发写入（预期水位）：条件 UPDATE，rowcount 必须为 1，否则 `session_watermark_conflict`（409）。
- [x] CAS 领取与取队首（保留）。（SQLite 已验证；PostgreSQL 随 2.9。）
- [x] 启动恢复：旧 epoch 的 `started` 与执行记录标记为 `unknown`，会话阻塞；显式解除与审计。（SQLite 已验证；PostgreSQL 随 2.9。）
- [x] 测试：快照读写、水位冲突（含两写者竞争）、非数据与超长载荷拒绝、未知版本拒绝（`tests/test_session_snapshot.py`）。CAS 领取与崩溃恢复已有测试。

## 执行与缓存（路线图第 3 步）

- [ ] 每 Run 新建执行对象；进程级共享模型客户端与工具注册表（按配置版本）。
- [x] 终态快照：成功、失败、取消、中断均在 Run 终态写入路径（`runs/completion.py::_finish`，同一事务）中保存 v2 快照，只记录 `last_run` 的稳定码并保留其他键；仍为 `running` 的工具调用标记 `interrupted`。等待态不保存。（未放在运行器 `finally` 中，因为运行器的 `finally` 不负责持久化终态。）
- [x] 投影缓存模块：key `(session_id, watermark)`，LRU、空闲 TTL、单条目字节上限，不缓存权限（`nexus_platform/sessions/projection_cache.py`，测试 `tests/test_projection_cache.py`）。接入运行时待做。
- [ ] 忙时策略（interrupt 默认，queue、steer 可选）与队列上限 32；`max_concurrent_sessions` 拒绝路径。
- [ ] 权限不缓存；每次工具调用查库。
- [ ] 测试：执行对象每 Run 新建；投影缓存命中与淘汰；快照三种结束方式；忙时策略；权限撤销即时生效。
- [ ] 测量装配耗时，确定 `max_entries`、`idle_ttl`、字节上限默认值。

## 文档与归档

- [ ] 同步更新架构文档 1.2、2.2、2.12 与路线图第 2、3 步。
- [ ] 归档本变更。
