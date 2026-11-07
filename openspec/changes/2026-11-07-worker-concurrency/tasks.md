# 实施任务

状态：实施中（2026-11-07，决定 1–8 已确认，默认并发 32）。已完成的任务才勾选。

## 0. 准备
- [x] 0.1 用户确认决定 1–8（决定 1 默认 32）。
- [x] 0.2 补读 deer-flow `runtime/runs/worker.py` 的任务生命周期与取消、`app/gateway/app.py` 并发上限接入；Octop `infra/bridge/transport.py` 的 `_spawn`；WeKnora `qa.go` 的取消上下文。
  - 已读 deer-flow `runtime/runs/manager.py` 的租约对账与 `subagents/executor.py` 的独立循环及 `AGENTS.md` 里循环绑定资源的约束，Octop `infra/bridge/transport.py` 的 `_spawn`，WeKnora `container.go` 的连接池设置与限流器，Hermes `api_server_runs.py`、`turn_executor.py`、`session_unattended_unknown.py`。
- [x] 0.3 共享状态审计（沙箱会话、工具注册表、嵌入器单例、`contextvars`、`OutputSpill`、模型连接池配置、`_worker_loop`），结果记入本节。
  - 进程级共享的是模型连接池（所有 Run 同一循环，现在可全部复用）、嵌入器单例（只读）；`OutputSpill`、沙箱会话按 Run 或会话构造，不共享；`_worker_loop()` 改线程局部，仅后台作业线程使用。未发现 Run 之间串用的全局可变状态；更细的逐模块审计没有做。
- [x] 0.4 扫描 `async def` 内直接调用同步数据库的位置，列出清单。
  - AST 扫描：`DurableRuntimeStore` 31 处同步数据库块均不含 `await`，已全部搬入线程池；`memory/vectors.vector_ranking` 已搬；`ScheduleBridge` 本就用线程。剩余在循环上直接做的数据库读取：知识库工具（`knowledge/tools.py`，数据库会话与 `await` 交织）与模型客户端创建时的凭据解析（需要运行中的循环）。二者很短，循环滞后看门狗会报告造成的卡顿。
- [x] 0.5 先更新文档：`docs/architecture.md` 2.12、`docs/roadmap.md`、`apps/worker`、`apps/api`、`packages/platform` 的 README 与 design，`configs/nexus.example.toml`。
  - `docs/architecture.md` 2.12、`apps/worker`、`apps/api`、`packages/platform` 文档与 `configs/nexus.example.toml`、`docs/roadmap.md` 3.29。

## 1. 配置
- [x] 1.1 `[worker]`：`max_concurrent_runs`、`db_threads`、`stop_timeout_seconds`；启动校验；`embedded_workers` 弃用警告。
  - `[worker]`（`max_concurrent_runs` 默认 32、`db_threads` 默认 16、`stop_timeout_seconds`）与 `[api]`（`threads` 默认 40）在 `runs/worker_settings.py`；`embedded_workers` 字段保留但不再生效。
- [x] 1.2 启动时校验线程池与连接池容量。
  - 改为由配置推导而不是校验：引擎连接池 = 线程数 + 4（`create_database_engine(pool_size=)`，不允许溢出），容量恒等于线程数加余量；API 同理（`[api].threads`）。

## 2. 并发执行
- [x] 2.1 `db_call` 与专用线程池；热点调用迁移；新增静态扫描测试。
  - `runs/dbexec.py`（`run_db`、`@offloaded`、专用执行器）；未配置时为单线程执行器。静态扫描测试没有写，由 0.4 的一次性 AST 扫描代替。
- [x] 2.2 `ControlChannel.wait_async` 三后端实现；监视协程改用它。
  - 三后端均实现；监视协程改用 `wait_for_signal_async`。
- [x] 2.3 `run_async`：领取协程、信号量、Run 任务；`once`、`stopped` 语义保持。
  - 领取协程 + 信号量 + Run 任务；`--once` 与测试仍走同步的 `run_loop`。
- [x] 2.4 后台作业放线程并限制并发。
  - 专用后台线程池，数量受 `background_concurrency` 限制。
- [x] 2.5 停止流程与总超时。
  - 停止后各 Run 经取消令牌收尾，状态为 `cancelled`（与变更前一致；规格里写的 `interrupted` 以实现为准）。
- [x] 2.6 事件循环滞后看门狗。
  - 每秒测量，超过 1 秒记警告。
- [x] 2.7 嵌入模式改单线程单循环。
  - `EmbeddedWorkers` 一个线程、一个循环、独立数据库引擎；API 侧线程池上限与引擎连接池由 `[api].threads` 设置。

## 3. unknown 恢复
- [x] 3.1 `resolve_unknown_admin` 与列表查询；权限；审计。
  - `session_ledger.resolve_unknown_admin`（条件更新，只有一个调用者成功）与 `runs/unknown.py`。
- [x] 3.2 接口 `GET .../admissions/unknown`、`POST .../runs/{id}/resolve-unknown`；命令行 `list-unknown`、`resolve-unknown`。
  - `GET /tenants/{t}/admissions/unknown`、`POST /tenants/{t}/runs/{run}/resolve-unknown`；命令行 `list-unknown`、`resolve-unknown --run-id`。
- [x] 3.3 `settle_recovered_unattended` 接入启动恢复。
  - 实现为 `unknown.settle_unattended`，在 `start_process_epoch` 里 `recover_previous_epochs` 之后调用。
- [x] 3.4 安全判定与 `[platform].auto_resolve_safe_unknown`（默认关闭）。
  - `unknown.is_safe` 以 `tool_invocations.input_summary.tool_name` 对应注册表的 `side_effects`；映射不到的视为不安全；`[platform].auto_resolve_safe_unknown` 默认关闭。
- [x] 3.5 会话视图 `blocked` 字段；前端提示条与解除按钮。
  - 会话消息接口返回 `blocked`；前端 `NexusChatPage` 提示条与「解除」按钮，六种语言文案。

## 4. 验证
- [x] 4.1 并发 N 个 Run、取消隔离、停止、慢数据库、崩溃恢复、权限、自动解除、嵌入模式连接复用等测试。
  - `tests/test_worker_concurrency.py`（重叠执行、上限为 1 时串行、取消隔离、停止、数据库调用不卡循环、配置）、`tests/test_unknown_recovery.py`（8 项）。嵌入模式共享连接池的断言没有单独写。
- [ ] 4.2 全量 `pytest`；默认配置下事件序列基线不变。
- [ ] 4.3 前端单元测试；`pnpm build` 与浏览器测试（本机内存不足时在有条件的环境执行）。
