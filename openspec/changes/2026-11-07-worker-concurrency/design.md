# 设计：Worker 并发执行与 unknown 会话恢复入口

状态：待确认。以下为推荐方案下的设计。

## 1. 并发执行模型

```text
现在                                     之后
run_loop (同步)                          run_async (一个事件循环)
  └ run_once                               ├ 领取协程：claim_next（线程池）→ 取到则起 Run 任务
      └ run_until_complete(Run)            │            无任务则按需运行后台作业，再等待
         （阻塞到 Run 结束）               ├ Run 任务 × N（信号量 = max_concurrent_runs）
                                           │    admit_or_defer → execute_native → after_run
                                           ├ 每个 Run 的监视协程（租约/取消/看门狗）
                                           └ 循环滞后看门狗
```

- 领取协程：信号量有空位才领取（`claim_next` 在线程池里执行）；没有空位时等待任一 Run 结束，不预先领取，避免租约空转。
- Run 任务：把现有 `run_once` 里 `execute_native` 之后的 `after_run` 一并放入任务内，任务结束释放信号量。
- `max_concurrent_runs = 1` 时，领取与执行的先后顺序和现在相同；同步入口 `run_once` 保留给测试与 `--once`；`stopped` 事件与 `once` 语义保持。
- `execute_native` 已是协程，不需要改写；改的是它的调用方与它内部的两类阻塞点（数据库、等信号）。

## 2. 同步数据库与线程池

- `store.py` 等处的同步事务保持不变，调用点统一经 `await db_call(fn, *args)`，它是 `loop.run_in_executor(db_executor, fn, *args)` 的薄封装；`db_executor` 为专用 `ThreadPoolExecutor(db_threads)`（未配置时为单线程执行器，保持测试里「同一连接的调用互不重叠」的语义），不占用默认执行器（默认大小 `min(32, cpu+4)`，会与 `asyncio.to_thread` 的其他使用争用）。
- 迁移方式：`DurableRuntimeStore` 中 31 处同步数据库块均不含 `await`（已用 AST 核对），22 个纯同步方法用 `@offloaded` 装饰器整体搬入线程池，含 `await` 的 5 个方法（`authorize`、`load_skill`、`exec_skill`、`read_skill_file`、`search_memory`）手工拆出同步块；`emit` 的临时事件分支不走线程。
- 热点调用：`DurableRuntimeStore.emit / message / commit / save_progress / heartbeat / watch`、`prepare_execution`、`admit_or_defer`、`claim_next`、`finish`。凡是在协程里直接调用同步数据库函数的地方，审计后全部包起来；新增一个测试扫描 `async def` 内的直接 `with factory()` 调用（白名单之外即失败）。
- 容量：启动时比较 `db_threads` 与引擎连接池可用连接数（SQLAlchemy `pool_size + max_overflow`；SQLite 文件库按 1 个写者计，仅警告），池不足则报错，防止线程池把连接池耗尽后互相等待。
- 取消语义：已放入线程池的同步事务无法中断，取消只在 `await` 返回处生效；事务本身很短（毫秒级），可接受。

## 3. 监视循环与控制通道

- `ControlChannel` 增加 `async def wait_async(run_id, timeout) -> bool`：
  - `MemoryControl`：每个 Run 一个 `asyncio.Event`，`signal` 经 `loop.call_soon_threadsafe` 置位（API 与 worker 同进程，API 侧的 `signal` 在另一个线程）。
  - `RedisControl`：使用 `redis.asyncio` 客户端的 `BLPOP`，一个 Run 一个等待者，不占线程。
  - `DatabaseControl`：`await asyncio.sleep(timeout)`。
  - 原同步 `wait` 保留给后台线程与测试。
- 监视协程每 0.2 秒检查 `stopped`，其余等待改为 `wait_async`，数据库租约检查仍按 `lease_check_seconds`。

## 4. 后台作业

`schedule_tick`、`knowledge_tick`、`capture_tick`、`consolidation_tick`、`embedding_tick` 内部使用同步数据库和 `asyncio.run`，保持原样，在线程里执行（`asyncio.to_thread`），同时运行的数量不超过 `background_concurrency`。运行条件不变：本轮没有领到 Run。线程里的 `asyncio.run` 使用线程局部事件循环，与主事件循环隔离。

## 5. 事件循环滞后看门狗

每秒 `await asyncio.sleep(1)` 并测量实际延迟；超过 `lease_check_seconds` 记录警告（含当前在执行的 Run 数），超过租约时长的四分之一记录错误。只观测不干预。

## 6. 停止

`stopped` 置位后：停止领取；对每个 Run 任务触发其取消令牌（沿用现有 `token.cancel()` 路径，Run 以 `interrupted` 收尾）；等待所有任务结束，总超时 `[worker].stop_timeout_seconds`（默认 30）；超时仍未结束的 Run 不强杀，租约到期后按现有流程回收。

## 7. 嵌入模式

```text
API 进程
  ├─ 事件循环 A：FastAPI
  └─ worker 线程：事件循环 B，run_async(max_concurrent_runs) + 通道 memory
```

`EmbeddedWorkers` 只起一个线程（循环内仍是协程并发），线程内 `asyncio.run(run_async(...))`。`embedded_workers` 弃用（见提案）。异常退避重启保持。

## 8. unknown 恢复

### 8.1 接口

| 方法与路径 | 说明 |
| --- | --- |
| `GET /tenants/{tenant_id}/admissions/unknown` | 列出租户内被 `unknown` 阻塞的会话：`admission_id`、`session_id`、`run_id`、Run 状态与中断时间、是否「安全」（见 8.3）。权限：租户 owner / admin；普通成员只看到自己的 |
| `POST /tenants/{tenant_id}/runs/{run_id}/resolve-unknown` | 解除该 Run 对应的 `unknown`，会话恢复。权限：Run 所有者、租户 owner / admin。幂等：已解除返回 200 与当前状态。审计 `run.unknown_resolved` |
| 命令行 `list-unknown` / `resolve-unknown --run-id` | 运维入口，绕过租户权限，审计执行者记为命令行操作者 |

`resolve_unknown` 需要当前进程的 `epoch`：API 进程没有 worker 的 epoch，改为在函数上新增 `resolve_unknown_admin`（不要求 epoch，按 `admission_id` 与状态 `unknown` 条件更新，rowcount 必须为 1），原函数保持给 worker 使用。

### 8.2 无人值守自动解除

`settle_recovered_unattended(db, epoch)`：在 `start_process_epoch` 里 `recover_previous_epochs` 之后调用，选出 `unknown` 记录中 Run 属于定时任务会话（`CronJobRecord.session_id`）的，条件更新为 `terminal` 并写审计（执行者为系统）。Run 本身已由租约回收标为 `interrupted`，不重复写。

### 8.3 无副作用自动解除（默认关闭）

判定「安全」：该 Run 的 `tool_invocations` 中没有状态为 `running` 且工具声明 `side_effects` 的记录。映射方式：`ToolInvocationRecord.operation_id` 与 `tool.started` 事件的 `invocation_id` 对应，事件载荷里有工具名，工具名在注册表里查 `side_effects`；映射不到的一律视为「不安全」。开启 `[platform].auto_resolve_safe_unknown` 后，启动恢复对安全的记录自动解除并写审计（执行者为系统，原因 `no_side_effect`）。列表接口始终返回安全标记，便于人工参考。

### 8.4 暂停提示

`GET /sessions/{id}/conversation` 增加 `blocked: {reason: "unknown", run_id, admission_id, interrupted_at} | null`；前端对被阻塞的会话显示提示条，有权限者显示「解除」按钮，调用 8.1 的接口。

## 9. 失败模式

| 情形 | 行为 |
| --- | --- |
| 进程崩溃 | N 个 Run 租约到期后被标 `interrupted`；N 条 `unknown`；定时任务会话自动解除，其余按 8.1 解除或（开启时）按 8.3 自动解除 |
| 事件循环被同步调用卡住 | 滞后看门狗告警；租约 60 秒，`lease_check_seconds` 为 1–5 秒，容忍短暂卡顿 |
| 线程池耗尽 | 数据库调用排队，Run 变慢但不失败；启动校验提前拒绝明显不合理的配置 |
| 单个 Run 抛异常 | 只影响该任务，其余继续；任务异常记日志，Run 按现有路径写 `failed` |
