# Run 事件通道与部署模式：数据库只存持久事实，实时流与控制信号走独立通道；支持嵌入模式；补强并发准入

## 状态

实施中（2026-11-07）：决定 1–10 全部采用推荐方案。实施中的调整与进度记录在 `tasks.md`。

## 原因

API 与 worker 是两个进程，目前全部经数据库交互，并发上来后压力集中在三处（已核对代码）：

1. **SSE 按连接轮询**：`apps/api/.../http/platform.py` 的流式接口每个连接每 0.25 秒查一次 `run_events`，且每轮重复 `get_run`（含权限校验）。1000 个观看者约 4000 QPS 纯读，并占用 1000 个同步线程与数据库连接。
2. **每个事件一个完整事务**：`runs/store.py` 的 `emit` 每次都开事务、检查 Outbox 租约、`FOR UPDATE` 锁 Run、写事件。流式文本 `message.delta` 默认每 150ms 一次（`delta_flush_ms`），单个流式 Run 约 7 事务/秒，200 个并发 Run 约 1400 事务/秒，且全部争用各自的 Run 行锁。
3. **控制信号靠心跳读库**：取消、审批结果由 worker 在心跳（`heartbeat()`）里读库发现，延迟取决于心跳周期。

4. **部署形态单一**：只有 API 与 worker 分进程一种形态。deer-flow、WeKnora 的 Run 与 API 同进程（deer-flow 是网关内的 asyncio 任务，WeKnora 是请求处理的 goroutine，只有后台作业走独立 worker 池），小规模部署没有跨进程成本。拆分的收益是重启不杀 Run、资源与扩缩隔离，且后台作业（定时、知识索引、记忆整理、向量化）必须有常驻进程；但对个人或小团队，这些收益用不上，跨进程成本却全要付。
5. **并发准入有缺口**：已有会话内 FIFO、全局活动会话上限（`[platform].max_concurrent_sessions`，默认 8，`runs/session_ledger.py`、`admission_repository.py`）。缺：按租户 / 用户的公平上限，以及按模型的并发限流（deer-flow 有全局与每用户 Run 上限；WeKnora 有按模型的 Redis 限流器，且只约束后台任务，不挤占交互聊天）。

数据库作 Outbox 队列本身不是瓶颈（行锁加租约，量级为每 Run 几次领取）。瓶颈是把「实时流」与「控制信号」也放在数据库里。

## 参考源码

| 项目 | 文件 | 借鉴点 |
| --- | --- | --- |
| deer-flow | `runtime/stream_bridge/base.py`、`redis.py`、`memory.py` | `StreamBridge` 抽象（publish / subscribe / cleanup）；Redis Streams，`XADD MAXLEN` 限长、`XREAD BLOCK` 批量读；`Last-Event-ID` 重连；缓冲被挤掉时返回 `StreamGap` 而不是静默丢事件；心跳哨兵；生产者租约与 Lua 比较后写入（围栏，过期 worker 不能再发布）；`ping` 就绪探测；`cleanup(delay)` 让晚到订阅者排空 |
| | `runtime/events/store/db.py`、`runs/manager.py` | 持久事件与实时流分离；`owner_worker_id` 与租约过期回收 |
| WeKnora | `internal/stream/redis_manager.go`、`memory_manager.go`、`factory.go` | 按环境选择 memory / redis；活动 Run 标记（`SetLiveRun` / `ClaimLiveRun` / `GetLiveRun`，活动期间续 TTL）；控制事件放独立 key（steer），不进用户可见流；`DropMessageStreams` 随会话删除清理 |
| | `internal/types/interfaces`（`StreamManager`）、`router/task.go` | 接口与实现分离；asynq 队列（不采用，见决定 8） |
| | `internal/container/container.go`（`registerModelConcurrencyLimiter`）、`router/task.go`（`backgroundTaskMiddleware`） | 按模型并发限流，后台任务与交互聊天区分对待 |
| deer-flow | `runtime/runs/manager.py`（`multitask_strategy`）、`app/gateway/app.py`（`max_concurrent_runs`、`max_concurrent_runs_per_user`） | 全局与每用户 Run 上限；同线程并发策略 |

两者取舍：deer-flow 的 Redis Streams 优于 WeKnora 的 Redis List 加偏移轮询（阻塞读、有序 ID、`MAXLEN`、断档可检测），采用前者作为数据面；WeKnora 的活动 Run 标记与独立控制通道是 deer-flow 没有的，采用后者补充。

## 范围

### 范围内

1. **核心契约**（`nexus_core`，无依赖）：`RunEventBus` 端口，含 `publish`、`publish_end`、`subscribe(run_id, after_id)`（产出事件、心跳、`StreamGap`、结束哨兵）、`cleanup`、`ping`、生产者租约（`start` / `renew` / `finish` / `state`）。`ControlChannel` 端口：向某个 Run 发送 `cancel`、`approval_resolved` 信号，worker 阻塞等待。
2. **三个后端**（平台包 `runs/bus/`）：
   - `database`：默认，零依赖。沿用数据库作事实来源，但改为每个 API 进程、每个 Run 只有一个共享轮询器，向该进程内所有订阅者扇出；间隔自适应（0.25→1 秒，空闲拉长）；连接时授权，之后每 30 秒复核而非每轮。
   - `redis`：Redis Streams，生产推荐。键 `nexus:run:{run_id}:events`，`MAXLEN ~` 限长，TTL 在 Run 结束后保留一段时间供重连。
   - `memory`：进程内，仅用于测试与 API 和 worker 同进程的嵌入运行；API 与 worker 分进程时配置此后端会在启动时报错。
3. **事件分级**：
   - **持久事件**（除 `message.delta` 外的全部）：保持现状，同一事务写库，提交后再发布到通道，ID 即 `sequence`。
   - **临时事件**（`message.delta`）：只发布到通道，不写库。临时事件不带 SSE `id:`，因此 `Last-Event-ID` 永远指向持久序号。
   - **新增持久事件 `message.completed`**（载荷 `{turn, text}`）：每个回合结束时，与该回合的助手消息在同一事务写入（`commit(events, message, progress)` 已支持）。原因：前端对已完成 Run 用 `listRunEvents` 读出持久事件，再由 `toAgentEventStream` 重建「回答 ↔ 工具」交错的时间线（`NexusChatPage.vue`、`utils/nexusAgentEvents.ts`）；`messages` 表只提供合并后的文本，不含交错顺序。没有它，`message.delta` 不写库会使历史时间线丢失回答文字。前端遇到 `message.completed` 时，把该回合的 `answer` 替换为完整文本并标记完成；`database` 后端下 `message.delta` 仍写库，两者一致，直接标记完成。
   - 通道发布失败只记日志和指标，不使 Run 失败；订阅者自动回退到数据库路径。
4. **订阅流程**（解决先放后读的竞态）：先记录通道尾部，再从数据库重放 `after_sequence` 之后的持久事件，再消费通道并按 `sequence` 去重。通道断档（`StreamGap`）时发送 `stream.resync` 事件，前端丢弃未完成的流式文本，以数据库中的消息为准。
5. **生产者围栏**（deer-flow）：worker 开始执行时在通道登记带令牌的生产者租约，心跳续期；发布走「令牌一致才写入」的 Lua；租约丢失后临时事件不再发布。持久事件仍由数据库租约围栏（不变）。订阅者可据生产者租约过期状态结束流（`stream.closed`），由客户端回落为查询 Run 状态。
6. **控制通道**（WeKnora）：取消与审批结果除写库外，同时向 `nexus:run:{run_id}:control` 发信号，worker 的心跳等待改为阻塞读该通道（超时仍回落读库），取消延迟从心跳周期降到毫秒级。控制信号不进入用户可见流。数据库仍是事实，通道丢信号不影响正确性。
7. **活动 Run 标记**（WeKnora）：`nexus:session:{session_id}:live` 记录当前正在生成的 Run，活动期间续 TTL，终态清除。新增 `GET /sessions/{id}/live-run`，前端打开会话时据此直接接入流，不必先扫描 Run 列表。会话与 Run 删除时清理其通道键。
8. **SSE 接口改为异步生成器**：不再一个连接占一个线程；数据库重放部分放线程池，通道部分用异步 Redis 客户端；心跳改为 15 秒的 SSE 注释行。
9. **配置**（`[run_events]`）：`backend`、`redis_url`、`maxlen`、`retention_seconds`、`heartbeat_seconds`、`poll_min_ms`、`poll_max_ms`；Redis 为可选依赖（extra `redis`）。启动时校验，无效配置阻止启动，与 `[knowledge]`、`[watchdog]` 一致。
10. **可观测**：指标 `run_event_publish_failures`、`run_event_gaps`、`run_event_subscribers`、`run_event_bus_up`；`/health/ready` 对非 `database` 后端调用 `ping`。
11. **嵌入模式**：新增 `[deployment].mode`，取 `embedded` 或 `split`（默认 `split`，行为不变）。`embedded` 下 API 进程在 lifespan 中启动 worker 循环（独立线程，复用同一个 `run_once` 与后台作业 tick），事件通道固定为 `memory`，不需要 Redis。同一份代码，仅启动方式不同。`embedded` 的约束：
   - 容量上限是单进程；重启时进行中的 Run 按现有租约机制恢复（租约到期后回收），不保证不中断。
   - 后台作业（知识索引、记忆整理、向量化）在嵌入模式下并发受 `[deployment].background_concurrency` 限制（默认 1），且仍只在空闲时运行，避免拖慢接口。
   - `run_worker` 当前在函数内注册 SIGINT / SIGTERM，非主线程不可用；拆为「循环主体」与「信号安装」两部分，嵌入时由 API 的 lifespan 控制停止事件。
   - 数据库引擎、模型连接池、嵌入器（`install_embedder`）在两进程模式下各自初始化，嵌入时共享同一进程内实例，需核对线程安全。
12. **并发准入补强**（在现有会话 FIFO 与全局上限之上，不替换）：
   - 每租户、每用户的活动会话上限（`[platform].max_concurrent_sessions_per_tenant`、`_per_user`，默认不限，设置后才生效，沿用 `LedgerError` 的稳定错误码）。
   - 按模型的并发限流（`[model_limits]`，默认关闭）：令牌取自 Run 准备阶段的模型配置，限流器放在模型调用前；只约束后台任务（记忆整理、摘要、向量化、知识增强），交互式 Run 不受限但计入用量；`redis` 后端用 Redis 计数，`database` 与 `memory` 用进程内计数（分进程且无 Redis 时按进程各自计数，文档注明）。
   - 超限不丢请求：交互式 Run 沿用会话 FIFO 排队；后台任务延后重试。
13. **文档**：`docs/architecture.md`、`docs/roadmap.md`、`apps/api`、`apps/worker`、`packages/core`、`packages/platform` 的 README 与 design，`configs/nexus.example.toml`。

### 范围外

- 不引入独立任务队列（asynq / Celery）：Outbox 行锁加租约已满足；领取频率与 Run 数同阶，不是瓶颈（决定 8）。
- 不采用 Postgres `LISTEN/NOTIFY`：它与 Redis 方案重叠，且 SQLite 不支持。`database` 后端已覆盖无 Redis 的场景。
- 不改 Run 状态机、不改事件的持久语义；不需要数据库迁移。历史 `message.delta` 行保持可读。

## 待确认的决定

1. **默认后端**：（推荐）`database` 为默认，`redis` 为生产推荐并可选启用；备选：强制 Redis。理由：本地开发零依赖，生产再升级，且 Redis 故障时能回退。
2. **`message.delta` 不再写库**：（推荐）采用；备选：仍写库但按更大窗口合并。采用后写库量下降最多（流式期间的主要写入），代价是进行中的半截文本只能从通道恢复，通道断档时只能看到已持久化的部分；回答文本在 `messages` 与 `run_events`（`message.completed`）各存一份。已用前端代码核对：历史时间线依赖事件而非消息，因此必须配套 `message.completed`。
3. **生产者令牌围栏**：（推荐）采用 deer-flow 的 Lua 比较写入；备选：只靠数据库租约，不围栏临时事件。
4. **控制通道**：（推荐）取消与审批走通道加数据库双写；备选：保持仅读库。
5. **活动 Run 标记与 `GET /sessions/{id}/live-run`**：（推荐）采用。
6. **Redis 作可选依赖**：（推荐）extra `redis`，`database` 后端不依赖它；备选：作为必选依赖。
7. **SSE 改异步**：（推荐）采用；这会改动认证依赖和会话注入方式，需随同改造 `get_database_session` 在流式接口中的使用（流内按需短会话，不持有长连接）。
8. **不引入独立队列、不用 NOTIFY**：（推荐）如范围外所述；备选：另起提案。
9. **嵌入模式**：（推荐）采用，默认仍为 `split`；备选：不提供，小规模部署同样起两个进程。
10. **并发准入补强**：（推荐）每租户 / 用户上限默认不限，按模型限流默认关闭，均为显式开启才生效；备选：仅做全局上限（现状）。

## 验收

- 后端契约测试对 `database`、`memory`、`redis`（`fakeredis`）三个实现跑同一套用例：顺序、去重、重连续传、断档、心跳、结束、围栏、清理。
- 压测脚本（沿用 deer-flow `scripts/benchmark/concurrency` 的做法）：同样的 N 个流式 Run、M 个观看者下，对比三个后端的数据库 QPS、事务数、首字延迟；`redis` 后端流式期间每 Run 的数据库写入应只剩持久事件与心跳。
- 杀掉 Redis、杀掉 worker、断开客户端各一次：Run 状态正确，客户端重连后文本完整。
- 取消延迟：`redis` 后端下从请求到 worker 停止低于 1 秒。
- 嵌入模式下单进程完成 Run 的全流程（提交、执行、流式、取消、审批、定时任务、知识索引），无 Redis；停止时优雅退出，不残留线程；多个用户同时流式互不影响。
- 并发准入：超出每用户 / 每租户上限时返回稳定错误码或排队；按模型限流只让后台任务延后，交互式 Run 不被后台任务饿死。
- 既有 Run、事件、SSE 测试保持通过。
