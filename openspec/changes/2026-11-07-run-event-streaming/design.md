# 设计：Run 事件通道

状态：待确认。以下为推荐方案下的设计。

## 1. 数据面与事实来源

```text
worker                                   API (async SSE)                     浏览器
  │ 持久事件：事务写库 ──提交后──► bus.publish(id=sequence)
  │ 临时事件(message.delta)  ───────► bus.publish(无 sequence)
  │                                      │ subscribe(run, after_sequence)
  │                                      │   ①记录通道尾部 ②库中重放持久事件 ③消费通道，按 sequence 去重
  │                                      └──────────────► SSE: id=<sequence> / 无 id / 心跳注释
  │ 心跳 ◄── control.wait(run) ◄── API 取消/审批：写库 + control.signal
```

- 数据库永远是事实来源。通道可丢、可断档、可整体不可用，丢了只影响实时性，不影响最终状态。
- 持久事件的 ID 是 `sequence`；临时事件没有 ID，因此客户端 `Last-Event-ID` 总指向一个持久序号，重连语义不变。

## 2. 契约（`nexus_core.run_events`）

```python
class RunEventBus(Protocol):
    async def publish(self, run_id, event: BusEvent) -> None          # 失败抛 BusUnavailable，由调用方吞掉并计数
    async def publish_end(self, run_id) -> None
    def subscribe(self, run_id, *, after: str | None, heartbeat: float) -> AsyncIterator[BusItem]
    async def cleanup(self, run_id, *, delay: float = 0) -> None
    async def ping(self) -> bool
    # 生产者租约（围栏）
    async def start_producer(self, run_id, owner: str) -> bool
    async def renew_producer(self, run_id, owner: str) -> bool
    async def finish_producer(self, run_id, owner: str) -> None
    async def producer_state(self, run_id) -> Literal["untracked", "active", "expired"]

BusItem = BusEvent | StreamGap | Heartbeat | End
class ControlChannel(Protocol):
    async def signal(self, run_id, kind: Literal["cancel", "approval_resolved"], data) -> None
    async def wait(self, run_id, timeout: float) -> list[ControlSignal]
class LiveRunMarker(Protocol):
    async def claim(self, session_id, run_id, ttl) -> bool
    async def touch(self, session_id, run_id, ttl) -> None
    async def get(self, session_id) -> UUID | None
    async def clear(self, session_id, run_id) -> None
```

三个端口放在一个契约模块，`database` 与 `memory` 后端对 `ControlChannel`、`LiveRunMarker` 提供退化实现（读库 / 进程内字典）。

## 3. 后端

### 3.1 `redis`（取 deer-flow）
- 键：`{prefix}:run:{id}:events`（Stream）、`:producer`（令牌）、`:control`（Stream）；`{prefix}:session:{id}:live`。
- 发布：`XADD MAXLEN ~ N`，字段 `kind`（event / end）、`event`、`data`。持久事件额外带 `seq`。围栏发布用 Lua：先比较 `:producer` 令牌，再 `XADD`。
- 订阅：`XREAD BLOCK heartbeat*1000 COUNT 64`；起点为 `after` 对应的 Stream ID；若 `after` 早于保留的最早 ID，产出 `StreamGap(requested, earliest, latest)` 后从尾部继续。瞬时 Redis 错误指数退避重试 3 次，之后向上抛，由 API 层回退到数据库路径。
- 租约：30 秒 TTL，每 10 秒续期，续期用 Lua 比较令牌；`producer_state` 区分 `untracked` / `active` / `expired`，用于判断流是否可以结束。
- 结束：`publish_end` 写结束条目；`cleanup(delay)` 在 `retention_seconds` 后删除，让晚到订阅者排空。

### 3.2 `database`（默认，加固现状）
- 每个 API 进程、每个活跃 Run 一个共享轮询器（`RunPoller`），首个订阅者创建，最后一个离开时销毁；扇出到各订阅者的内存队列。
- 间隔自适应：有新事件时 `poll_min_ms`，连续空轮询时逐步增大到 `poll_max_ms`。
- 临时事件在此后端不存在（没有地方放）：`message.delta` 退化为仍写库，保持与现状一致。因此 `message.delta` 的「不写库」只在 `redis` / `memory` 后端生效，写入路径由后端能力 `supports_ephemeral` 决定。
- 权限：连接时授权一次，之后每 30 秒复核，失效即发 `stream.closed`。

### 3.3 `memory`
- 进程内事件日志加 `asyncio` 条件变量，容量 `maxlen`，结构对应 deer-flow `MemoryStreamBridge`。
- 启动时检测：API 与 worker 分进程部署（`apps/api` 与 `apps/worker` 各自启动）配置为 `memory` 即报错，防止静默无流。

## 4. 订阅流程与去重

```text
async def stream(run, after_sequence):
    tail = await bus.tail(run)                      # ① 先占位，防止 ② 与 ③ 之间漏事件
    async for row in db_replay(run, after_sequence): yield durable(row); last = row.sequence
    async for item in bus.subscribe(run, after=tail_or_start):
        durable 事件: seq <= last → 丢弃，否则 yield 并更新 last
        临时事件: 只在其 turn 的持久消息尚未出现时转发
        StreamGap: 追加一次 db_replay(last)，yield stream.resync
        Heartbeat: yield ": heartbeat"
        End: 终态后收尾
```

- 进行中半截文本的恢复：订阅起点取「当前 turn 的第一个临时事件」之前（通道保留 `maxlen` 条内），因此中途重连可重放该 turn 已输出的文本；超出保留窗口则 `StreamGap`，前端以数据库消息为准。
- `stream.resync` 的语义：前端清空当前未完成的流式缓冲，随后收到的持久事件是权威。

## 5. 写入路径改造（`runs/store.py`）

- `emit(kind, payload)`：
  - 临时事件（且后端 `supports_ephemeral`）：校验本地缓存的租约状态（不开事务），直接 `bus.publish`；租约状态由心跳线程刷新。
  - 持久事件：现有事务不变；事务提交后（`SqlAlchemyUnitOfWork` 退出后）发布，失败吞掉。
- `commit(events, message, progress)`：同一事务写入，提交后批量发布其中的持久事件。
- 回合结束的 `commit` 的 `events` 中加入 `message.completed {turn, text}`（`text` 为该回合助手消息的文本部分）；与消息行同事务。
- `heartbeat()`：先 `control.wait(run, timeout=心跳周期)`，收到信号立即读库确认；超时按原逻辑读库。同时续期生产者租约与活动 Run 标记。
- 终态：写库的终态事件提交后 `publish_end`、`marker.clear`、`bus.cleanup(delay=retention)`。

## 6. API 变化

- `GET /runs/{id}/events`：`Accept: text/event-stream` 时走异步订阅；JSON 模式分页读库，不变。新增 SSE 事件 `stream.resync`、`stream.closed`（已有）。
- `GET /sessions/{id}/live-run`：返回 `{run_id, status}` 或 204。
- `/health/ready`：附带 `run_event_bus` 状态。
- 流式接口内不持有请求级数据库会话：授权、重放用短会话，避免长连接占用连接池。

## 7. 前端

- `toAgentEventStream` 新增 `message.completed`：同一 `turn` 已有开放的 `answer` 则把内容替换为完整文本并标记完成，没有则新建一个已完成的 `answer`（历史回看路径）。`stream.resync` 清空未完成（`done=false`）的 `answer`。
- `nexusAgentEvents` 处理无 `id` 的临时事件与 `stream.resync`；`EventSource` 的自动重连用最后一个持久 `id`。
- 打开会话时调 `live-run` 接入进行中的流。

## 8. 失败模式

| 故障 | 行为 |
| --- | --- |
| Redis 不可用 | 发布失败计数；订阅回退数据库路径；`ready` 报告降级；Run 不受影响 |
| worker 崩溃 | 数据库租约到期回收（不变）；通道生产者租约到期，订阅者收到 `stream.closed` |
| 订阅者落后 | `StreamGap`，补读数据库，`stream.resync` |
| 控制信号丢失 | 心跳回落读库，延迟退化为心跳周期，不丢取消 |
| 过期 worker 继续发临时事件 | Lua 令牌比较失败，被拒绝；持久事件被数据库租约拒绝（不变） |

## 9. 嵌入模式

```text
split（默认）：  apps/api ──► DB / Redis ◄── apps/worker           （现状 + 事件通道）
embedded：       apps/api 进程
                   ├─ FastAPI（事件循环）
                   └─ WorkerThread：run_loop(stop_event) ── memory 事件通道（进程内）
```

- `nexus_worker.__main__` 拆为 `run_loop(factory, worker_id, stopped, ...)`（循环主体，不装信号）与 `run_worker(...)`（装信号并调用 `run_loop`）。`split` 行为不变。
- API 的 lifespan：`mode == "embedded"` 时创建 `stop_event` 与守护线程运行 `run_loop`，退出时置位并等待（有超时）；线程内异常记录日志并按退避重启循环，不拖垮 API。
- 事件通道在嵌入模式固定为 `memory`；`[run_events].backend` 与 `[deployment].mode` 冲突（如 `embedded` + `redis` 允许，作为可选加速；`split` + `memory` 报错）在启动时校验。
- 后台作业并发受 `background_concurrency` 限制；`run_once`（Run 执行）优先，后台 tick 仍只在无待处理 Run 时运行（现有逻辑不变）。
- 线程安全核对项：SQLAlchemy 引擎（线程安全）、会话（每次工作新建，不跨线程）、模型 HTTP 连接池（`configure_connection_pool` 只在进程内初始化一次）、`install_embedder` 的单例、`_worker_loop()` 的独立事件循环。

## 10. 并发准入补强

- 现状：`session_ledger` 每会话 FIFO，`max_concurrent_sessions` 全局上限；占用槽位的状态为 `queued / started / unknown`。
- 新增 `TenantQuota` 检查，在 `admission_repository` 提交流程中、全局上限之后执行：统计该租户 / 用户占用槽位的会话数，超限抛 `LedgerError` 子类（稳定错误码 `tenant_session_limit`、`user_session_limit`）。上限为空即不检查。
- 按模型限流 `ModelLimiter`：`acquire(model_profile_id, kind)` 返回许可，`kind` 为 `interactive` 或 `background`；只对 `background` 阻塞（超出并发则任务保持未领取，下个 tick 重试），`interactive` 不阻塞但计数。许可带过期时间，worker 崩溃后自动回收。`redis` 后端用带 TTL 的计数键，其余后端用进程内计数。
