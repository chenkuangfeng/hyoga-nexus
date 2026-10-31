# 设计

## 一、分析结论与推荐点

以下每一条都是待确认的推荐，确认后写入对应规格。

| # | 推荐 | 理由 | 来源 |
|---|---|---|---|
| R1 | 权限判断不缓存，每次工具调用与资源访问查数据库 | 撤销权限需要立即生效；架构原则 2 要求每次调用重新授权；`ToolGateway` 只能收紧权限 | 架构 1.1、2.2 |
| R2 | 会话数据由所有者进程缓存，所有者期间不读库取会话数据 | 满足"不要每次从数据库读取"；所有权是唯一写入者，缓存无需修订号校验 | Hermes `_agent_cache` 的思路，但缓存数据而非整个 Agent |
| R3 | 所有权用 lease + epoch，每次写库 fencing | 进程崩溃或网络分区后，旧进程的延迟写入必须被拒绝 | Hermes `runtime_epoch`、`_epoch()` 检查 |
| R4 | 领取 Run 用 CAS + rowcount，不用先查后改 | 避免两个 worker 同时领取同一 Run | Hermes `claim_session_input`；本项目已有 SKIP LOCKED，PG 下两者可并存 |
| R5 | 上一代 epoch 的执行标记 `unknown`，不自动重放，会话阻塞 | 工具可能已产生副作用，重放有风险；与架构 2.12 "中断不重放" 一致 | Hermes `recover_session_inputs` |
| R6 | 同会话 Run 串行。忙时新输入默认打断（interrupt）；排队（queue）、转向（steer）为可选。若有子任务或压缩进行中，打断降级为排队 | 与 Hermes 一致：默认 `interrupt`（`run_config_loaders.py:250`），TUI 默认 `queue`（`session_setting_commands.py:38`）；降级规则见 `run_inbound.py` 的 `_hm_handle_running_session_message` | Hermes |
| R7 | 排队有界：每会话待处理队列上限 32，超限丢弃并记录；全局活跃会话上限 `max_concurrent_sessions`，超限直接拒绝新会话并返回提示，不排队 | 与 Hermes 一致：`_BUSY_QUEUE_MAX_PENDING = 32`（`gateway/run.py:3738`）、`ADMISSION_QUEUE_MAX = 32`（`hermes_state_runtime.py:121`）、拒绝路径（`run_inbound.py:1306`） | Hermes |
| R7a | 持久化 FIFO 按 `seq` 取队首；队首被他人占用时返回 False，调用方重读 | Hermes `claim_session_input` 的 `head` 校验（`hermes_state_runtime.py:200-230`） | Hermes |
| R7b | queue、steer 模式下的排队输入在进程重启后保留；interrupt 模式下的输入丢弃 | Hermes `_queue_during_drain_enabled`（`gateway/run_busy.py`） | Hermes |
| R8 | 回复按请求 ID 路由，不使用全局回调广播 | 避免跨会话回复串线 | GenericAgent `ga.py:574` 的教训 |
| R9 | 群聊默认按参与人隔离会话，线程可共享 | 避免群内 A 的上下文泄露给 B | Hermes `group_sessions_per_user` |
| R10 | 缓存只存数据，超过上限后按 LRU 淘汰，淘汰后从库重建 | 缓存丢失不影响正确性 | 本提案 |
| R11 | 派发端口（dispatch、notify、gate、fanout）定义接口，PG 为首个实现，Redis 不引入 | PG 的 SKIP LOCKED、CAS、计数行可覆盖派发与门控；Redis 只在测量证明需要时再加 | 本项目 2.12 D1、D2 |
| R12 | Outbox 与 `FOR UPDATE SKIP LOCKED` 保留为 PG 的派发实现 | 已在架构中确定 | 架构 2.12 |

## 二、会话所有权

### 获取与心跳

- 所有者在本进程内对每个持有的会话维护心跳，间隔 `T_hb`，过期时间 `T_exp > 3 * T_hb`。
- 获取：`UPDATE session_owners SET owner_id=:me, epoch=epoch+1, expires_at=now()+T_exp WHERE session_id=:s AND (owner_id=:me OR expires_at < now())`，rowcount 为 1 即成功，返回新 epoch。
- 释放：空闲 TTL 到达或进程正常退出时，将 `expires_at` 设为过去，允许其他进程立即接管。

### 所有者期间的读写

- 首次获取所有权时，从库全量装配会话数据并写入缓存（记录 epoch）。
- 之后 Run 期间不读库取会话数据；只读取本进程缓存。
- 写入顺序：先写库（带 `owner_epoch`），提交成功后更新缓存。写库失败或 `stale_epoch` 时丢弃该会话缓存并停止该会话的执行。
- 心跳失败或发现 epoch 不一致：立即丢弃缓存，中断本进程对该会话的执行，执行记录标记 `unknown`（R5）。

### 边界说明

"不从数据库读取"只对会话数据成立。以下操作仍然访问数据库，属于协议本身需要：所有权获取与心跳、派发 CAS、Run 事件与账本写入、权限检查、冷启动或接管时的一次性全量装配。

## 三、派发账本与恢复

状态机（admission）：`queued → started → terminal`；崩溃或接管时 `started → unknown`。

- 领取：`UPDATE ... SET status='started', owner_epoch=:e WHERE id=:id AND status='queued' AND session 无 started/unknown`，rowcount 必须为 1。
- 启动恢复：所有 `owner_epoch < 当前 epoch` 的 `started` 记录与执行记录改为 `unknown`，会话阻塞。
- 解除阻塞：仅通过显式操作（用户确认或运维命令），不自动重放。解除时记录审计事件。
- 与现有规则的关系：架构 2.12 "中断不重放" 保持不变；`unknown` 是对"中断"的明确状态，便于界面展示和人工处理。

## 四、会话缓存内容

键：`session_id`。值：

| 字段 | 内容 | 失效 |
|---|---|---|
| `epoch` | 获取所有权时的 epoch | 所有权变化时丢弃 |
| `history_view` | 事件投影后的消息视图（含压缩摘录） | 本进程写入时更新 |
| `checkpoint` | 工作检查点 | 本进程写入时更新 |
| `bindings` | 智能体版本、模型配置版本、记忆快照引用 | 绑定变化由所有者写入时更新 |
| `exec_config` | 无状态执行配置：模型客户端、工具注册表（不含授权结果） | 配置版本变化或 TTL |

Run 对象（如 `NativeEngine`）是否缓存见第六节待确认项。

## 五、容量与回收

- 进程级上限：`max_sessions`，超出按 LRU 淘汰，淘汰前释放所有权。
- 单条目字节上限：超出时只保留检查点与最近 N 条消息，较早内容按需读库（仍是只读，不改变所有权）。
- 空闲 TTL：`idle_ttl` 内无 Run 的会话释放所有权并删除缓存。
- 默认值待测量确定。

## 六、需要用户确认的决定

1. **权限是否缓存（R1）**：推荐不缓存。若坚持"全部不读库"，权限撤销会有最长一个缓存周期的延迟，与架构原则 2 冲突。
2. **Run 对象是否缓存**：Hermes 缓存整个 Agent 对象。推荐缓存无状态执行配置（exec_config），Run 对象每次重建；若要缓存 Run 对象，它必须只持有可重建的数据，且恢复逻辑不依赖它。
3. **所有权是否改变领取规则（R2、R4）**：推荐改为"所有权感知领取"。代价是 worker 之间的会话亲和性，以及接管延迟（最多一个 `T_exp`）。
4. **同会话新输入默认策略（R6）**：已按 Hermes 定为打断（interrupt），queue、steer 为可选。注意这与之前推荐的"排队"不同，需确认。
5. **队列参数（R7）**：已按 Hermes 定为每会话 32、全局 `max_concurrent_sessions`（默认不限，由配置设定）。Hermes 没有排队超时，本方案也不加超时，除非确认需要。
6. **群聊隔离（R9）**：推荐默认按参与人隔离。

## 七、测试要点

- 所有权：并发获取只有一方成功；过期接管后 epoch 递增；旧 epoch 写入被拒绝（`stale_epoch`）。
- 派发：两个 worker 同时 CAS 领取同一 Run，只有一方成功。
- 恢复：模拟进程崩溃后重启，`started` 变为 `unknown`，会话阻塞，不自动重放。
- 缓存：所有者期间 Run 不产生会话数据读库（用查询计数断言）；接管后从库全量重建。
- 权限：撤销权限后，同会话下一次工具调用被拒绝。
- 容量：超过 `max_sessions` 后 LRU 淘汰，淘汰后结果与库一致。
- 重启：缓存为空，行为与缓存命中时一致。
