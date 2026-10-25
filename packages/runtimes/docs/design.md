# Runtime 设计

Native Engine 保持原有执行循环。模型适配在 `native/models/openai_compatible.py`，安全网络客户端在 `native/models/network.py`，由应用入口注入，不依赖 platform。

PinnedTransport 校验 URL 与每次请求的 origin，在发送前解析 DNS，拒绝任何非全局地址，随后连接经过校验的字面 IP，同时保留 Host 与 TLS SNI/证书域名检查，避免重新 DNS 解析绕过校验。禁止重定向和隐式环境代理。DNS 超时为 5 秒；模型/测试请求还有独立截止时间。部署可用 `NEXUS_MODEL_PRIVATE_HOST_ALLOWLIST` 显式允许指定主机私有地址与 HTTP，仅在可信私有模型部署时配置。

通过 httpx transport 注入假 HTTP 的既有 Provider 单元测试仍可执行；用户配置的真实请求由 API/worker 装配安全 transport。

完整参考实现迁移尚未完成，实际缺口和拟采用的模块划分见 [双项目审计](../../../docs/pending/native-reference-audit.md)。`reference-source-inventory.tsv` 的未审查项仍是待办；不得把当前单类循环视作两个项目的完整等价实现。

## Native 迁移批次

`engine/runner.py` 统一组织预算、回合、结束判断与恢复；`turn.py` 校验模型流，`completion.py` 处理空响应、重复与代码澄清，`tools.py` 提供默认顺序执行和显式只读并发屏障，`recovery.py` 消费挂起调用并更新错误预算与工作检查点。`__init__.py` 保留原导入入口。

`context/working.py` 管理工作锚点和周期提醒，`compaction.py` 在配置启用时生成摘要并保留源记录；失败降级为有界历史片段。`hooks/` 提供可信注册与追加上下文/完成提示，不能扩大资源授权。模型模块按协议、文本工具解析、重试和路由分离，支持 Chat Completions、Responses、Anthropic Messages；流已输出后不重新拼接重试结果。协议测试目前使用 HTTP 夹具，尚未证明真实供应商兼容性。

配置由不可变 AgentVersion 快照注入。来源、许可证、验证和未完成范围见 [本批记录](../../../docs/pending/native-reference-parity/verification.md)。

## 模型失败、终态和用量

`models/errors.py` 使用受限结构化 code/type 和 HTTP 状态分类，不解析自由文本。公开异常只含稳定码；内部 ModelFault 保留 Retry-After、缓冲前是否已输出及禁止恢复标记，兼容 RuntimeFault 消费点而不修改 core。HTTPX 响应 hook 在 SDK 读取拒绝正文前限制为 64 KiB；结构化适配器也有独立读取上限。两种传输均释放响应，SDK 自身重试关闭。

`protocols/state.py` 管理单响应调用身份、参数、块闭合与终态，`structured.py` 只组织 HTTP、可见文本与结果交付。Responses 使用 item_id/回退 output_index 聚合，并以 call_id 关联工具结果；Anthropic 保留初始 input、要求工具块闭合，允许有效 stop reason 后 EOF。Chat 保持严格 finish_reason；DONE 哨兵不足以独立证明完成。结构化显式 failed/error、未知状态、缺终态、坏 JSON 均不得变成正常完成。

`engine/turn.py` 在模型结果收集后拒绝 content_filter，包括同时携带工具的响应；length 工具沿既有 runner 恢复路径不执行。文本工具包装器在过滤/截断时保留该原因，不从标签恢复调用；上游已经输出但尚在缓冲的失败也会阻止外层重试/切换。调用方通过 aclosing 及时关闭异步流。

`retry.py` 与 `routing.py` 仅恢复 timeout、rate_limited、provider_unavailable，HTTP 暂时集合为 408/429/500/502/503/504。认证、参数、额度、context 和未知显式失败不做传输重试。Retry-After 支持秒和 HTTP 日期；超过已有最大延迟直接禁止本次恢复，不提前重试。模型 timeout/Run 活跃预算包住整个请求与等待，取消可打断等待。部分流失败不会拼接另一个供应商，后续请求才可能使用备用节点。

`usage.py` 接受缺失/null 为未知零值，计数必须是 0..2**53-1 的 JSON 整数，拒绝布尔、字符串、负数、分数和越界。Responses/Chat 缺 total 时用 input+output，Anthropic 用 input+cache_read+cache_creation+output；有效显式 total 包括零值予以保留。累计输出快照覆盖而非累加，Anthropic 输入/缓存计数不会被输出尾块清零。零/缺用量时 Native 仍按既有方式估算预算；不能由计数零推断真实免费调用，也不宣称已观测失败尝试的真实供应商消耗。

已确认的上游差异和逐文件归属见 [来源映射](../../../third_party/model-terminal-mapping.md)。完整模型签名/历史、供应商兼容参数、多模态和 cache 状态治理不在此局部修复的完成声明内。
