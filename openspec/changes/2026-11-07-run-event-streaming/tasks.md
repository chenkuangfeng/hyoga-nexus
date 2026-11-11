# 实施任务

状态：实施中（2026-11-07，决定 1–10 已确认）。已完成的任务才勾选。

## 0. 准备
- [x] 0.1 用户确认决定 1–10（全部采用推荐方案）。
- [ ] 0.2 补读 deer-flow `stream_bridge/redis.py` 的 `subscribe`、围栏与清理，`runs/worker.py` 的发布与租约接入；WeKnora `redis_manager.go` 的 live-run 与 steer 部分。
  - 仅读了 `base.py`、`redis.py` 的结构与常量、围栏脚本和 `memory` 的接口，没有逐行读完 `subscribe` 与 `runs/worker.py`；Redis 后端按其结构自行实现并用 `fakeredis` 测试。
- [x] 0.3 核对：助手消息作为 `messages` 行整条持久化，但前端历史时间线由持久事件重建（`listRunEvents` → `toAgentEventStream`），`messages` 只作兜底；因此决定 2 必须配套持久事件 `message.completed`（见 3.1、5.1）。
- [x] 0.5 核对嵌入模式的线程安全项（见设计 9），尤其 `run_worker` 的信号安装、引擎与嵌入器初始化顺序、`_worker_loop()`。
  - `_worker_loop()` 改为线程局部；`run_worker` 的信号安装留在 `run_worker`，循环主体拆为 `run_loop`；每个嵌入线程独立事件循环。发现并记录：一个 worker 同一时刻只执行一个 Run，并发 Run 数等于 worker 数，因此嵌入模式新增 `embedded_workers`（默认 4）。
- [x] 0.6 补读 deer-flow `app/gateway/app.py` 的并发上限接入与 `scheduler`；WeKnora `registerModelConcurrencyLimiter` 与 `backgroundTaskMiddleware`。
  - 已读 `app/gateway/app.py` 的并发上限配置、WeKnora `registerModelConcurrencyLimiter` 与 `backgroundTaskMiddleware`。
- [x] 0.4 先更新文档：`docs/architecture.md`、`docs/roadmap.md`、`apps/api`、`apps/worker`、`packages/core`、`packages/platform` 的 design 与 README。
  - `docs/architecture.md` 2.12、`docs/roadmap.md` 3.28、`apps/api`、`apps/worker`、`packages/core`、`packages/platform` 的 README / design，`configs/nexus.example.toml`。

## 1. 契约与配置
- [x] 1.1 `nexus_core.run_events`：端口、`BusEvent`、`StreamGap`、哨兵；契约无外部依赖。
  - `publish` 为同步（由提交钩子与 worker 线程调用），`subscribe` 为异步。
- [x] 1.2 `[run_events]` 配置与启动校验；`configs/nexus.example.toml`；`redis` extra。
  - `[run_events]`、`[deployment]` 读取器在 `runs/bus/config.py`；`redis` extra 与 dev 依赖（`fakeredis[lua]`）在根 `pyproject.toml`，`uv.lock` 已更新。

## 2. 后端
- [x] 2.1 `memory` 后端与分进程部署的启动检查。
  - 分进程部署配置 `memory` 在读取配置时即报错。
- [x] 2.2 `database` 后端：共享轮询器、自适应间隔、定期复核授权。
  - 共享轮询器按（事件循环，Run）建立，最后一个订阅者离开即销毁；间隔自适应 `poll_min_ms` 到 `poll_max_ms`。授权复核在订阅管线的静默期状态检查里（每 1 秒一次短会话），不再每轮重查。
- [x] 2.3 `redis` 后端（共享读取器在 8.1 压测中才真正补上，此前每个订阅者各读一次）：发布、订阅、断档、围栏租约、清理、`ping`、瞬时错误重试；每个进程每个 Run 一个读取器再扇出到订阅者（与 `database` 后端的共享轮询器一致）。
  - 发布走同步客户端并带 5 秒熔断；订阅走异步客户端。
- [x] 2.4 `ControlChannel`、`LiveRunMarker` 三后端实现。
  - 范围调整：控制信号只有 `cancel`。审批与输入响应后 Run 已停在 waiting 状态并由 Outbox 重新投递，worker 没有在等它们，所以不发信号。
- [x] 2.5 契约测试：三后端同一套用例（`fakeredis`）。
  - `tests/test_run_events.py`，redis 部分用 `fakeredis`。

## 3. 写入路径
- [x] 3.1 `store.py`：持久事件提交后发布；回合结束的 `commit` 加入 `message.completed {turn, text}`；临时事件走通道；失败吞掉并计数。
- [x] 3.2 `heartbeat()` 接入控制通道、生产者租约、活动标记续期。
- [x] 3.3 取消与审批接口双写控制信号。
  - 取消：`request_cancel` 写库的 `run.cancel_requested` 事件提交后，钩子发 `cancel` 信号（不改取消代码本身）。审批与输入不发信号，见 2.4。
- [x] 3.4 终态收尾：`publish_end`、清标记、延迟清理；会话与 Run 删除清理键。
  - `End` 与取消信号由提交钩子在终态 / 等待事件提交后发布；活动标记在 `stream_finish` 清除。会话与 Run 删除时清理通道键依赖 TTL 过期，未做主动删除。

## 4. API
- [x] 4.1 SSE 异步订阅与 `stream.resync`；流内短会话。
  - 授权后立即 `db.close()`，之后只开短会话。
- [x] 4.2 `GET /sessions/{id}/live-run`；`/health/ready` 报告。
  - 就绪探测 `/api/v1/ready` 附带 `run_event_bus`（非 database 后端：ok / degraded）。
- [ ] 4.3 指标。
  - 未做：目前只有日志（发布失败、断档、通道不可用均记警告），没有指标端点；仓库当前没有指标基础设施，留待统一接入。

## 5. 前端
- [x] 5.1 `toAgentEventStream` 支持 `message.completed`（替换并完成 / 历史回看新建）；无 `id` 事件、`stream.resync`、`live-run` 接入；单元测试覆盖「只有 completed 无 delta」「delta 与 completed 同时存在」「resync 后以 completed 为准」。
  - 前端未调用 `live-run`：`loadSession` 已经用会话的 `latest_run` 接入进行中的 Run，接口留作其他客户端使用。`vue-tsc` / 浏览器测试见 8.3。

## 6. 嵌入模式
- [x] 6.1 `run_worker` 拆为 `run_loop` 与信号安装；`split` 行为用现有 worker 测试证明不变。
- [x] 6.2 `[deployment]` 配置、校验与冲突检查；API lifespan 启停 worker 线程，异常退避重启，优雅退出。
  - `embedded.py`：每线程独立 worker_id，崩溃按 5 秒退避重启。
- [x] 6.3 嵌入模式端到端测试：提交、流式、取消、审批、定时任务、知识索引；多用户并发；停止后无残留线程。
  - 测试覆盖提交、执行、停止无残留线程；多用户并发、审批、定时任务、知识索引沿用各自既有测试，未在嵌入模式下重复。

## 7. 并发准入
- [x] 7.1 每租户 / 用户上限与稳定错误码；默认不限，沿用账本规则与现有测试。
- [x] 7.2 `ModelLimiter` 与 `[model_limits]`；后台任务延后重试；`redis` 与进程内两种计数。
  - 接入记忆抽取、记忆整理、知识库聊天三个后台调用点；Redis 计数用带过期的有序集合。
- [x] 7.3 测试：超限、崩溃后许可回收、交互式不被饿死。

## 8. 验证
- [x] 8.1 压测脚本与三后端对比数据记入 `docs`。
  - 脚本 `evals/run-events/bench.py`，数据与结论在 `packages/platform/docs/run-events-benchmark.md`。压测发现并修复四个问题：memory 后端先于首个事件连上的查看者要等下一个心跳；redis 后端每个查看者各占一个阻塞读取与连接，与任务 2.3 声明的共享读取器不符（100 个订阅者 p50 从 65.6 ms 降到 1.4 ms）；共享读取器的订阅队列加上限，读得慢的查看者被切断并回退到数据库；新连接跳过无谓的断档检查。
- [x] 8.2 故障注入：Redis、worker、客户端。
  - `tests/test_run_events_faults.py`，对真实 `redis-server`（可杀、可重启；无该程序时跳过）：Redis 中途被杀与重启、查看者断开与卡住、worker 租约过期与僵尸围栏、结束标记与过期。整套 worker 进程被杀后的恢复由既有账本与租约测试覆盖，不在此重复。
- [ ] 8.3 全量 `pytest`、`pnpm build` 与浏览器测试。
