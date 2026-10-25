# Runtime 设计

Native Engine 保持原有执行循环。模型适配在 `native/models/openai_compatible.py`，安全网络客户端在 `native/models/network.py`，由应用入口注入，不依赖 platform。

PinnedTransport 校验 URL 与每次请求的 origin，在发送前解析 DNS，拒绝任何非全局地址，随后连接经过校验的字面 IP，同时保留 Host 与 TLS SNI/证书域名检查，避免重新 DNS 解析绕过校验。禁止重定向和隐式环境代理。DNS 超时为 5 秒；模型/测试请求还有独立截止时间。部署可用 `NEXUS_MODEL_PRIVATE_HOST_ALLOWLIST` 显式允许指定主机私有地址与 HTTP，仅在可信私有模型部署时配置。

通过 httpx transport 注入假 HTTP 的既有 Provider 单元测试仍可执行；用户配置的真实请求由 API/worker 装配安全 transport。
