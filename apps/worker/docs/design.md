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

## 上下文组合

`execute_native` 调用平台的 `ContextPreparationService.prepare_async`：短 DB 阶段使用数据库池，外部记忆等待使用独立线程，不持有 SQLAlchemy Session。外部同步 hook 的执行和排队共用四个容量令牌，超时后直到底层函数实际结束才释放，迟到结果不提交；snapshot/prefetch 共享八秒 deadline。外部记忆实现可用 `register(provider, generation="version")` 声明稳定版本以复用重启前快照，不指定时采用进程实例版本并安全重建。暂时暂停调用与撤销提供方权限分开，短暂故障不会让已有合法快照被误判为撤权。

内置处理器仍进程级共享，`ToolRegistry.fork()` 为每个 Run 创建独立注册映射，MCP 注册不修改共享 builtin 表；发给模型的 schema 深拷贝。初始目录授权支持一次批量操作，调用时再检查资源或 MCP 当前状态。MCP 使用服务绑定和当前 schema/风险指纹授权，不伪造普通工具 ResourceBindingRecord ID。

可信应用可通过 `execute_native(..., context_providers=registrations)`（同步 `run_once` 或 `run_async.execution_options` 同样支持）传入 ProviderRegistration。注册时明确 name、generation、lifetime、大小、超时与 system_allowed；会话/Run 资料按来源校验后复用，step 资料随模型 step 生成。应用停用实现时从组合入口移除该注册并调用 `unregister_plugin_generation`，其旧来源在下一请求失效；重新部署的 generation 必须显式一致才能复用。该入口不接受模型参数、上传路径或任意第三方代码。
