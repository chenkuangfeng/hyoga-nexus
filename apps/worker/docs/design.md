# Worker 设计

`native.py` 作为组合根装配模型、工具和持久化服务。StoredCredentialResolver 仅允许当前 Run 的主体解析所绑定模型的凭据，并复核空间和个人归属；非 encrypted 引用委托已有环境解析器。

模型客户端使用 Runtime 的 PinnedTransport，默认 HTTPS，禁用环境代理和重定向；仅对部署端明确允许的主机开放私有地址/HTTP。密文不可解析时转换为稳定 `model_credential_unavailable`，不把底层异常写入事件。

worker 启动时通过 platform 配置模块自动读取 `configs/nexus.toml`，无需加载 `.env`；配置错误在进入任务循环前由 CLI 报告，不包含连接秘密。

## 嵌入模式与监视循环

- `run_worker` 装信号并调用 `run_loop`；`run_loop` 不碰信号，可在线程中运行。`_worker_loop()` 为线程局部事件循环，嵌入的每个线程各有一个。
- Run 的监视循环（`native.py` 的 `monitor`）每 0.2 秒检查停止信号，并阻塞等待通道的取消信号（`store.wait_for_signal`）；数据库租约续期与取消检查每 `lease_check_seconds` 一次，收到信号则立即检查。
- 执行开始时登记生产者租约与会话活动标记（`store.stream_start`），结束后释放（`stream_finish`）；临时事件 `message.delta` 在通道支持时只发布到通道。
