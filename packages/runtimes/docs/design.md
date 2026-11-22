# Runtime 设计

Native Engine 保持原有执行循环。模型适配在 `native/models/openai_compatible.py`，安全网络客户端在 `native/models/network.py`，由应用入口注入，不依赖 platform。

PinnedTransport 校验 URL 与每次请求的 origin，在发送前解析 DNS，拒绝任何非全局地址，随后连接经过校验的字面 IP，同时保留 Host 与 TLS SNI/证书域名检查，避免重新 DNS 解析绕过校验。禁止重定向和隐式环境代理。DNS 超时为 5 秒；模型/测试请求还有独立截止时间。部署可在 `configs/nexus.toml` 的 `[model_network].private_host_allowlist` 中显式允许指定主机私有地址与 HTTP，仅在可信私有模型部署时配置。

通过 httpx transport 注入假 HTTP 的既有 Provider 单元测试仍可执行；用户配置的真实请求由 API/worker 装配安全 transport。

完整参考实现迁移尚未完成，后续设计见 [总体架构](../../../docs/architecture.md)。当前实现不代表两个项目的完整等价迁移。

## Native 迁移批次

`engine/orchestrator.py` 的 `RunOrchestrator` 实现 `nexus_core.runtime.AgentRuntime` 端口（`capabilities()` 与 `run(RunRequest, RunContext)`），负责运行生命周期、预算、取消、事件持久化与回合循环；它把单回合工作委托给以下组件：`turn.py` 的 `TurnExecutor` 组装请求并收集模型流；`context/assembler.py` 的 `ContextAssembler` 负责压缩（在 turn.before 钩子之前）、回合视图（之后），并在 Run 开始时冻结工具定义；`completion.py` 的 `CompletionJudge` 把每个响应判定为 `JudgeDecision` 之一（执行工具、接受、接受截断、空响应重试、不完整工具调用、停滞、失败）；`dispatcher.py` 的 `ToolDispatcher` 处理一批工具结果：审批挂起、错误计数、工作检查点、终态与续写提示；`tools.py` 的 `execute_batch` 提供顺序执行与只读并发屏障；`recovery.py` 的 `resume_tools` 保留独立的恢复路径（结果映射与普通回合不同，合并会改变行为）。参数校验由工具网关完成，调度器不重复校验。`__init__.py` 导出 `CancellationToken`、`cancellable` 与 `RunOrchestrator`。

`context/working.py` 管理工作锚点和周期提醒，`compaction.py` 在配置启用时生成摘要并保留源记录；失败降级为有界历史片段。`hooks/` 提供可信注册与追加上下文/完成提示，不能扩大资源授权。模型模块按协议、文本工具解析、重试和路由分离，支持 Chat Completions、Responses、Anthropic Messages；流已输出后不重新拼接重试结果。协议测试目前使用 HTTP 夹具，尚未证明真实供应商兼容性。

配置由不可变 AgentVersion 快照注入。模型局部修复的验证和未验收范围以本模块文档与 Git 历史为准（原 OpenSpec 批次记录已删除，见提交 `2a9ee03`）。

## 模型失败、终态和用量

Chat Completions 将已有模型版本的空字符串思考强度视为使用服务商默认行为，请求中省略该字段。

`models/errors.py` 使用受限结构化 code/type 和 HTTP 状态分类，不解析自由文本。公开异常只含稳定码；内部 ModelFault 保留 Retry-After、缓冲前是否已输出及禁止恢复标记，兼容 RuntimeFault 消费点而不修改 core。HTTPX 响应 hook 在 SDK 读取拒绝正文前限制为 64 KiB；结构化适配器也有独立读取上限。两种传输均释放响应，SDK 自身重试关闭。

`protocols/state.py` 管理单响应调用身份、参数、块闭合与终态，`structured.py` 只组织 HTTP、可见文本与结果交付。Responses 使用 item_id/回退 output_index 聚合，并以 call_id 关联工具结果；Anthropic 保留初始 input、要求工具块闭合，允许有效 stop reason 后 EOF。Chat 保持严格 finish_reason；DONE 哨兵不足以独立证明完成。结构化显式 failed/error、未知状态、缺终态、坏 JSON 均不得变成正常完成。

`engine/turn.py` 在模型结果收集后拒绝 content_filter，包括同时携带工具的响应；length 工具沿既有编排恢复路径不执行。文本工具包装器在过滤/截断时保留该原因，不从标签恢复调用；上游已经输出但尚在缓冲的失败也会阻止外层重试/切换。调用方通过 aclosing 及时关闭异步流。

`retry.py` 与 `routing.py` 仅恢复 timeout、rate_limited、provider_unavailable，HTTP 暂时集合为 408/429/500/502/503/504。认证、参数、额度、context 和未知显式失败不做传输重试。Retry-After 支持秒和 HTTP 日期；超过已有最大延迟直接禁止本次恢复，不提前重试。模型 timeout/Run 活跃预算包住整个请求与等待，取消可打断等待。部分流失败不会拼接另一个供应商，后续请求才可能使用备用节点。

`usage.py` 接受缺失/null 为未知零值，计数必须是 0..2**53-1 的 JSON 整数，拒绝布尔、字符串、负数、分数和越界。Responses/Chat 缺 total 时用 input+output，Anthropic 用 input+cache_read+cache_creation+output；有效显式 total 包括零值予以保留。累计输出快照覆盖而非累加，Anthropic 输入/缓存计数不会被输出尾块清零。零/缺用量时 Native 仍按既有方式估算预算；不能由计数零推断真实免费调用，也不宣称已观测失败尝试的真实供应商消耗。

已确认的上游行为差异原记录于已删除的 OpenSpec 批次设计（见提交 `2a9ee03`）。完整模型签名/历史、供应商兼容参数、多模态和 cache 状态治理不在此局部修复的完成声明内。

## 行为补齐（native-engine-behaviour）

- 截断的最终文本由 `CompletionJudge` 判定为 `CONTINUE_TRUNCATED`，编排器追加续写提示并发出 `answer.continued`；续写计数在任一完整响应或工具回合后清零，超过 `max_continuations` 后接受截断答案（`answer.truncated`）。
- 最后一个允许回合（`progress.turns >= max_rounds`）：模型请求的工具定义为空，视图追加"工具已禁用"提示，发出 `turn.tools_disabled`；模型仍返回的工具调用不执行，记为未执行。
- 模型请求计数：编排器在 Run 开始时把 `AttemptCounter` 绑定到 `RetryModel`（`bind_attempts`）。每次真实请求（含传输重试）先调用 `begin_attempt`，计数写入 `progress.model_attempts` 并发出 `model.attempt`；超过 `max_model_attempts`（0 时为 `max_rounds * (model_retries + 1)`）则不发送并以 `budget_exhausted` 结束。
- 待办工具 `todo` 通过 `RunServices.run_state` 访问 `progress.state`（与进度同一对象）；工具权限仍由网关每次复核。
- 工具循环检测（提案 2026-11-06-tool-call-hardening C，`engine/tool_guardrails.py`）：`ToolDispatcher` 对每个结果计算签名（工具名、规范化参数、结果前 2000 字符），相同签名连续出现或周期 2–4 循环时在第 `tool_repeat_warn_at` 次及其后两次各追加一次提醒，第 `tool_repeat_stop_at` 次以 `tool_loop_detected` 结束 Run；同一工具连续失败第 `tool_repeat_warn_at` 次提醒、第 `tool_failure_stop_at` 次结束，该工具成功或其他副作用工具成功时清零。状态在 `progress.state['tool_guard']`，用户追加指令或带答复恢复时清零；阈值为 0 关闭。审批恢复路径不计入。`ToolDispatcher` 每轮开始调用网关 `begin_turn()`。
