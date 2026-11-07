# Worker 并发执行与 unknown 会话恢复入口

## 状态

实施中（2026-11-07）：决定 1–8 已确认。决定 1 的默认值改为 32，决定 3 确认嵌入模式用协程（见下）。实施中的调整与进度记录在 `tasks.md`。

## 原因

1. **一个 worker 同一时刻只执行一个 Run**：`apps/worker/.../__main__.py` 的 `run_once` 用 `run_until_complete(execute_native(...))` 阻塞到 Run 结束才领下一个。并发 Run 数等于 worker 进程（嵌入模式为线程）数。Agent 的大部分时间在等模型、工具与沙箱，一个 Run 独占一个进程或线程，资源利用率低。
2. **嵌入模式的多线程带来连接池问题**：共享模型连接池按事件循环绑定（`nexus_runtimes/native/models/network.py` 的 `pool if owner is loop else None`），每个线程各有事件循环，只有先创建池的线程能复用连接，其余线程每次调用都重新握手。
3. **每个 Run 的监视循环占用线程**：`native.py` 的 `monitor` 每 0.2 秒 `asyncio.to_thread(store.wait_for_signal)`，并发上去会占满默认线程池。
4. **`unknown` 会话没有解除入口**：worker 崩溃后，`recover_previous_epochs` 把旧代次的 `started` 记录转为 `unknown`，会话被阻塞；`resolve_unknown` 只有函数与测试，没有 API、命令行或界面。定时任务会话（`is_scheduled_session`）没有人会去重发，崩溃一次就永久卡住。协程化后一个进程里有 N 个 Run，崩溃一次会留下 N 个 `unknown`，问题成倍放大。

## 参考源码

| 项目 | 文件 | 借鉴点 |
| --- | --- | --- |
| deer-flow | `runtime/runs/worker.py`、`manager.py`（`owner_worker_id`、租约、`reconcile_orphaned_inflight_runs`、`multitask_strategy`）；`app/gateway/app.py`（`max_concurrent_runs`、`..._per_user`） | Run 是网关内的 asyncio 任务；租约过期后由存活进程用条件更新对账，孤儿 Run 自动终止，线程不被阻塞；全局与每用户并发上限；异步数据库 |
| WeKnora | `internal/handler/session/qa.go`、`internal/container/container.go`（`SetMaxOpenConns`） | goroutine 并发；用数据库连接池上限控制并发访问，而不是限制 Run 数 |
| Octop | `infra/bridge/transport.py`（`_spawn`）、`infra/db/lease.py` | 每个 turn 一个协程，注释强调长任务不得阻塞接收与心跳循环；租约与续期时间常量 |
| Hermes | `gateway/platforms/api_server_runs.py`、`api_server.py`（`max_concurrent_runs` 默认 10，超限 429）；`session_authority.py`、`hermes_state_runtime.py`（`recover_session_inputs`）；`api_server_authority_runs.py`（`POST /v1/runs/{id}/resolve-unknown`）；`session_unattended_unknown.py` | Nexus 账本的来源；解除入口、无人值守来源在启动恢复时自动解除、暂停时提示一次。注意 Hermes 的 Run 是「每个 Run 一个线程」，不是协程，并发模型只作对照 |
| GenericAgent | `agentmain.py` | 单实例严格串行，不作参考 |

## 范围

### 范围内

**A. 协程化 worker**
1. **并发执行**：新增 `[worker].max_concurrent_runs`（默认 32）。实际并发还受 `[platform].max_concurrent_sessions`（默认 8）限制：同一会话同时只执行一个 Run，所以默认配置下最多 8 个 Run 同时执行；要用满 32 需同时调大会话上限。SQLite 数据库是单写者，其有效并发固定为 4 并记录警告。`run_loop` 改为异步：一个事件循环里领取任务，用信号量限制在执行的 Run 数，每个 Run 一个任务（准入、`execute_native`、`after_run`）。
2. **同步数据库访问**：保留同步 SQLAlchemy，所有数据库调用经专用线程池（`[worker].db_threads`，默认 16；Run 大部分时间在等模型而不是查库，不需要与并发数成倍数）。引擎连接池按 `db_threads + 4` 设置（`pool_size`，`max_overflow` 为 0 时的上限即此值）；启动时校验引擎连接池容量不小于线程池大小。未配置时（测试、命令行）数据库调用使用单线程执行器，保持与变更前相同的串行语义。
3. **监视循环**：每个 Run 一个协程；控制通道增加异步等待接口（memory 用 `asyncio.Event` 经 `call_soon_threadsafe` 唤醒，redis 用异步客户端阻塞读，database 用 `asyncio.sleep`），不再每个 Run 占一个线程。
4. **后台作业**（定时、知识索引、记忆抽取与整理、向量化）：这些函数内部使用 `asyncio.run` 或同步循环，放进线程执行，同一时刻最多 `background_concurrency` 个，仍只在没有可领取的 Run 时运行。
5. **取消与停止**：单个 Run 取消只终止它自己的任务；进程停止时取消所有 Run 任务，各自按现有路径收尾（状态为 `cancelled`，与变更前一致）并释放租约，有总超时。
6. **事件循环滞后看门狗**：周期性测量循环调度延迟，超过租约检查间隔时记警告并输出指标日志，防止同步阻塞拖垮所有 Run 的心跳。
7. **嵌入模式**：一个线程、一个事件循环，循环内用协程并发执行多个 Run，并发由 `max_concurrent_runs` 决定。不直接共用 API 自己的事件循环，是为了隔离：worker 一旦有偶发的同步阻塞会拖慢所有 HTTP 与 SSE 响应。上一变更（`2026-11-07-run-event-streaming`）加入的 `[deployment].embedded_workers` 被替换：仍可读取并给出弃用警告，值大于 1 时按 `max_concurrent_runs` 取较大者。
8. **连接池**：进程内只有一个事件循环，共享模型连接池全部可用；`_worker_loop()` 的线程局部实现保留给后台作业线程使用。
9. **共享状态审计**：逐项检查进程级全局状态在多 Run 并发下是否安全（沙箱会话、工具注册表、嵌入器单例、`contextvars`、`OutputSpill`、模型连接池配置），结果记入 `tasks.md`，需要修改的随本变更修。

**B. `unknown` 会话恢复入口**
1. **解除接口与命令行**：`POST /tenants/{tenant_id}/runs/{run_id}/resolve-unknown`（调用 `resolve_unknown`，审计沿用 `run.unknown_resolved`）；`GET /tenants/{tenant_id}/admissions/unknown` 列出被阻塞的会话与被中断的 Run；命令行 `resolve-unknown`、`list-unknown`。
2. **无人值守来源自动解除**：启动恢复在 `recover_previous_epochs` 之后，把属于定时任务会话的 `unknown` 记录直接转为 `terminal`（审计执行者为系统）。理由同 Hermes `session_unattended_unknown.py`：没有人可以被问「要不要重发」。
3. **可选的无副作用自动解除**：`[platform].auto_resolve_safe_unknown`（默认关闭）。开启后，被中断的 Run 若没有任何有副作用的工具调用处于未完成状态，启动恢复自动解除；其余仍需人工。判定规则与实现方式见 `design.md`。
4. **暂停提示**：会话视图增加 `blocked`（原因、Run、admission id）；前端在被阻塞的会话显示提示与「解除」按钮，仅对有权限者显示。

**C. 配置与文档**：`[worker]` 配置节、`configs/nexus.example.toml`、`docs/architecture.md` 2.12、`apps/worker`、`apps/api`、`packages/platform` 的文档。

### 范围外

- 不把平台迁移到异步 SQLAlchemy（deer-flow 的做法）：平台包的服务函数几乎全是同步的，改动面远超本变更，且线程池足以满足目标并发（决定 2）。
- 不做 Hermes 式的崩溃后自动续跑（`resume_pending`）：续跑会重放可能有副作用的操作，与账本「不自动重放」的原则冲突，作为后续议题。
- 不做单个 Run 内的并行；不做跨 worker 的负载均衡（仍由 Outbox 领取决定）。
- 不改 Outbox、租约、账本的状态机与表结构，不需要数据库迁移。

## 待确认的决定

1. **协程并发，默认 `max_concurrent_runs = 32`**（用户指定）：已确认。默认值变大意味着多个 worker 进程的部署中每个进程都可能同时执行多个 Run，运维需按需下调；实际并发仍受会话上限约束。备选：只给分进程模式加线程数（改动小，但连接池与线程占用问题不解决）。
2. **同步数据库走专用线程池**：（推荐）采用；备选：迁移到异步 SQLAlchemy（改动面过大）。
3. **嵌入模式改为单线程单循环，`embedded_workers` 弃用**：（推荐）采用；备选：保留多线程。
4. **崩溃影响面**：并发数越大，一次崩溃留下的 `unknown` 越多。已确认：默认 32 下实际受会话上限 8 约束，文档建议按可承受的崩溃影响调低，并配合 B 部分的入口与自动解除降低人工量；备选：不设上限提示，由运维自行承担。
5. **`unknown` 的自动解除**：（推荐）无人值守来源默认自动解除；无副作用自动解除默认关闭、显式开启；其余保持人工。备选：全部保持人工，只提供入口。
6. **解除权限**：（推荐）Run 所有者与租户 owner / admin；备选：仅平台管理员。
7. **事件循环滞后看门狗**：（推荐）采用，只记日志，不干预 Run。
8. **后台作业放线程执行**：（推荐）采用；备选：全部改写为原生协程（改动面大）。

## 验收

- 默认配置下现有测试全部通过，事件序列不变（测试以 `run_once` 同步入口驱动，不要求并发）。
- `max_concurrent_runs = N` 时同进程同时执行 N 个 Run：一个 Run 的取消、失败、模型超时不影响其余；总耗时接近单个 Run 而非 N 倍。
- 模拟慢数据库调用：事件循环滞后看门狗告警，但心跳与租约不丢（数据库调用在线程池内）。
- 进程停止：所有 Run 写 `interrupted`、释放租约，无残留任务。
- 崩溃恢复：N 个 Run 转为 `unknown`；定时任务会话自动解除；有人提交的会话阻塞，经接口解除后恢复；无权限者被拒；解除写审计。
- 开启无副作用自动解除：仅无未完成副作用调用的 Run 被解除。
- 嵌入模式：单线程完成多个 Run，共享连接池被所有 Run 复用（以连接创建次数断言）。
