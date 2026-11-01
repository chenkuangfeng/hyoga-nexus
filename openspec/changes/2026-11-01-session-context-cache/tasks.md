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

- [x] 每 Run 新建执行对象：`worker/native.py::execute_native` 每次新建引擎、工具网关、工具注册表和模型客户端。
- [x] 进程级共享工具注册表：`builtins()` 进程内只构建一次；存储通过 `ToolContext.services` 按调用传入，处理器不再闭包捕获 store，缺失时以 `tool_unavailable` 失败关闭（测试 `tests/test_shared_builtins.py`）。
- [ ] 进程级共享模型客户端：**未实施**。模型客户端每次构建前都重新检查凭据（`configured_routing`），这是有意设计，缓存客户端会在凭据被撤销后继续使用旧凭据。工具注册表绑定 store，共享需改变工具绑定契约；实测每 Run 构建注册表约 6.7 ms（timeit，`builtins(None)`，2000 次平均），相对模型调用可忽略，因此暂不共享。
- [x] 终态快照：成功、失败、取消、中断均在 Run 终态写入路径（`runs/completion.py::_finish`，同一事务）中保存 v2 快照，只记录 `last_run` 的稳定码并保留其他键；仍为 `running` 的工具调用标记 `interrupted`。等待态不保存。（未放在运行器 `finally` 中，因为运行器的 `finally` 不负责持久化终态。）
- [x] 投影缓存模块：key `(session_id, watermark)`，LRU、空闲 TTL、单条目字节上限，不缓存权限（`nexus_platform/sessions/projection_cache.py`，测试 `tests/test_projection_cache.py`）。接入运行时待做。
- [x] 忙时策略：默认排队（不打断），队列上限 32（已由 busy-session-queue 变更实现）。注意：本文件原文写的是“interrupt 默认”，与已确认的 busy-session-queue 冲突，以后者为准。steer 仅在 running 时接受。
- [x] `max_concurrent_sessions` 拒绝路径：提交新会话时计数，超限返回 503 `session_capacity_exceeded`（测试 `tests/test_session_capacity.py`）。PostgreSQL 下的并发精确性随 2.9 补齐。
- [x] 权限不缓存；每次工具调用查库（`ToolAccess.authorize` → `authorize_run_resource`，代码已核对；撤销即时生效的专门用例尚未补充）。
- [ ] 测试：执行对象每 Run 新建；投影缓存命中与淘汰；快照三种结束方式；忙时策略；权限撤销即时生效。
- [x] 测量装配耗时：工具注册表约 6.7 ms/Run。`max_entries`、`idle_ttl`、字节上限的默认值（256 / 900 s / 256 KiB）是估计值，尚未用真实负载校准。

## 文档与归档

- [ ] 同步更新架构文档 1.2、2.2、2.12 与路线图第 2、3 步。
- [ ] 归档本变更。
