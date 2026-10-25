# Worker 设计

`native.py` 作为组合根装配模型、工具和持久化服务。StoredCredentialResolver 仅允许当前 Run 的主体解析所绑定模型的凭据，并复核空间和个人归属；非 encrypted 引用委托已有环境解析器。

模型客户端使用 Runtime 的 PinnedTransport，默认 HTTPS，禁用环境代理和重定向；仅对部署端明确允许的主机开放私有地址/HTTP。密文不可解析时转换为稳定 `model_credential_unavailable`，不把底层异常写入事件。

worker 启动时通过 platform 配置模块自动读取 `configs/nexus.toml`，无需加载 `.env`；配置错误在进入任务循环前由 CLI 报告，不包含连接秘密。
