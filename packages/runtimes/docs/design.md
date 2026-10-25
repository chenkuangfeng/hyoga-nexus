# Runtime 设计

Native Engine 保持原有执行循环。模型适配在 `native/models/openai_compatible.py`，安全网络客户端在 `native/models/network.py`，由应用入口注入，不依赖 platform。

PinnedTransport 校验 URL 与每次请求的 origin，在发送前解析 DNS，拒绝任何非全局地址，随后连接经过校验的字面 IP，同时保留 Host 与 TLS SNI/证书域名检查，避免重新 DNS 解析绕过校验。禁止重定向和隐式环境代理。DNS 超时为 5 秒；模型/测试请求还有独立截止时间。部署可用 `NEXUS_MODEL_PRIVATE_HOST_ALLOWLIST` 显式允许指定主机私有地址与 HTTP，仅在可信私有模型部署时配置。

通过 httpx transport 注入假 HTTP 的既有 Provider 单元测试仍可执行；用户配置的真实请求由 API/worker 装配安全 transport。

完整参考实现迁移尚未完成，实际缺口和拟采用的模块划分见 [双项目审计](../../../docs/pending/native-reference-audit.md)。`reference-source-inventory.tsv` 的未审查项仍是待办；不得把当前单类循环视作两个项目的完整等价实现。

## Native 迁移批次

`engine/runner.py` 统一组织预算、回合、结束判断与恢复；`turn.py` 校验模型流，`completion.py` 处理空响应、重复与代码澄清，`tools.py` 提供默认顺序执行和显式只读并发屏障，`recovery.py` 消费挂起调用并更新错误预算与工作检查点。`__init__.py` 保留原导入入口。

`context/working.py` 管理工作锚点和周期提醒，`compaction.py` 在配置启用时生成摘要并保留源记录；失败降级为有界历史片段。`hooks/` 提供可信注册与追加上下文/完成提示，不能扩大资源授权。模型模块按协议、文本工具解析、重试和路由分离，支持 Chat Completions、Responses、Anthropic Messages；流已输出后不重新拼接重试结果。协议测试目前使用 HTTP 夹具，尚未证明真实供应商兼容性。

配置由不可变 AgentVersion 快照注入。来源、许可证、验证和未完成范围见 [本批记录](../../../docs/pending/native-reference-parity/verification.md)。
