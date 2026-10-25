# Worker 设计

`native.py` 作为组合根装配模型、工具和持久化服务。StoredCredentialResolver 仅允许当前 Run 的主体解析所绑定模型的凭据，并复核空间和个人归属；非 encrypted 引用委托已有环境解析器。

模型客户端使用 Runtime 的 PinnedTransport，默认 HTTPS，禁用环境代理和重定向；仅对部署端明确允许的主机开放私有地址/HTTP。密文不可解析时转换为稳定 `model_credential_unavailable`，不把底层异常写入事件。
