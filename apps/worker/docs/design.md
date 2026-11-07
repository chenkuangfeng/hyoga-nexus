# Worker 设计

`native.py` 作为组合根装配模型、工具和持久化服务。StoredCredentialResolver 仅允许当前 Run 的主体解析所绑定模型的凭据，并复核空间和个人归属；非 encrypted 引用委托已有环境解析器。

模型客户端使用 Runtime 的 PinnedTransport，默认 HTTPS，禁用环境代理和重定向；仅对部署端明确允许的主机开放私有地址/HTTP。密文不可解析时转换为稳定 `model_credential_unavailable`，不把底层异常写入事件。

worker 启动时通过 platform 配置模块自动读取 `configs/nexus.toml`，无需加载 `.env`；配置错误在进入任务循环前由 CLI 报告，不包含连接秘密。

## 嵌入模式与监视循环

- `run_worker` 装信号后 `asyncio.run(run_async(...))`；`run_async` 在一个事件循环里领取并以协程并发执行 Run（信号量 = 有效并发数，有空位才领取，不持有无人执行的租约）；`--once` 与测试用同步的 `run_once` / `run_loop`。`_worker_loop()` 为线程局部事件循环，仅供后台作业线程使用。
- 同步数据库调用经 `nexus_platform.runs.dbexec.run_db`（专用线程池，未配置时为单线程）；`DurableRuntimeStore` 的纯数据库方法用 `@offloaded` 整体搬入线程池，`emit` 的临时事件不走线程。尚未搬离循环的有：模型客户端创建时的凭据解析（需要循环）与知识库工具里混合 `await` 的数据库读取，二者很短，循环滞后看门狗会报告它们造成的卡顿。
- 后台作业（定时、知识索引、记忆抽取与整理、向量化）在专用线程里运行，数量受 `background_concurrency` 限制。
- Run 的监视循环（`native.py` 的 `monitor`）每 0.2 秒检查停止信号，并异步等待通道的取消信号（`wait_for_signal_async`，不占线程）；数据库租约续期与取消检查每 `lease_check_seconds` 一次，收到信号则立即检查。
- 停止：不再领取，置位 `stopped` 让各 Run 的监视取消令牌（Run 以 `cancelled` 收尾，与以往一致），最多等 `stop_timeout_seconds`，仍未结束的由租约到期回收。
- 执行开始时登记生产者租约与会话活动标记（`store.stream_start`），结束后释放（`stream_finish`）；临时事件 `message.delta` 在通道支持时只发布到通道。
