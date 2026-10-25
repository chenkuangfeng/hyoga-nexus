# 模型结果归一设计

## 范围和职责

模型协议负责 wire→core chunks；共享 errors/usage 模块负责无厂商类型的分类和计数；retry/routing 只消费可重试分类与有界等待；Native 收集器在协议结果验证成功后才交付可执行工具。保留现有工厂、导入和配置入口，不在 SDK 外另套执行循环，不把所有逻辑堆进 structured.py。

优先只修改 runtimes 内部结构。若 RuntimeFault 需携带 retry_after，作为可选内部字段添加，保持 RuntimeFault(code) 和 str(error) 兼容；不得进入错误文本或公开返回原始供应商响应。实现前核对 core 约束和全部消费点。

## 来源、冲突与决策

| 行为 | GA 锁定行为 | WK 锁定行为 | 本批选择与兼容证据 |
| --- | --- | --- | --- |
| 部分输出失败 | 传输异常可能重试，错误文本判路由 | 流 Fail，不在协议层统一重发 | Nexus 保持输出后不重发；验证调用数与部分文本不重复 |
| HTTP 拒绝 | 数字状态白名单重试 | JSON helper 不重试 HTTPError | 永久错误一次；408/429/500/502/503/504 在输出前允许重试；计数测试 |
| Chat DONE-only | 宽松解析 | 接受哨兵而无 finish_reason | 保持 Nexus 严格失败；明确兼容收紧，测试固定 |
| Responses EOF | 无统一终态门禁 | 缺 completed/incomplete 为 incomplete | RuntimeFault(model_stream_invalid)，保留部分文本，不执行工具 |
| Anthropic 工具开放 | 可返回未闭合块 | 过滤开放块并标 incomplete | 结果失败、不交付任何可执行调用；完整零参数调用保留 |
| Responses 截断+工具 | 可仍携带工具 | finishReason 优先 tool_calls | length 优先；保留既有不执行截断调用的恢复路径 |
| Done 事件 | response 默认 stop_reason | Process/End 可重复 Done | core 一次 done；不改变平台事件协议 |

WK HTTP retry helper 适用 JSON 请求，不冒称其为全部聊天策略。所有未采用行为保持在差异记录，不将本批归档当作全量迁移完成。

## 错误分类

| 输入 | RuntimeFault.code | 允许重试/切换 |
| --- | --- | --- |
| 超时 | model_timeout | 未输出时，预算内 |
| 网络连接失败 | model_provider_unavailable | 未输出时，预算内 |
| HTTP 408/500/502/503/504 | model_provider_unavailable | 未输出时，预算内 |
| HTTP 429，且非明确永久额度耗尽 | model_rate_limited | 未输出时，预算内 |
| HTTP 401/403 | model_authentication_failed | 否 |
| HTTP 400/404/405/409/422 等其他拒绝 | model_request_rejected | 否 |
| 结构化 context_length_exceeded | model_context_exceeded | 不做传输重试，保持已有上下文恢复语义 |
| 明确额度耗尽 insufficient_quota | model_quota_exhausted | 否 |
| 已知 JSON/SSE failed/error | 按受限结构化 code/type 映射，默认 model_response_failed | 默认否；只有已知暂时分类允许预输出重试 |
| 坏 JSON、坏工具结构、缺终态/矛盾终态 | model_stream_invalid | 否 |
| 过滤/refusal | content_filter→既有 model_content_filtered | 否，工具不执行 |

不按未经约束的自由文本猜错误类别；错误响应读取有大小界限，稳定码进入事件，正文、header、凭据不进入公开异常。HTTP 2xx 的显式失败即使携带文本/工具/usage，也必须先按失败判定，不发正常 done。

Retry-After 支持非负数字秒和 HTTP 日期，受已有 max_retry_delay_seconds 与剩余耗时预算约束；超过允许等待时直接结束该请求的恢复，不缩短后提前重试。缺失/无效/过去日期使用已有指数退避。等待可取消，取消后关闭流且不产生下一次请求；SDK 内建重试继续关闭。

## 终态与工具

- Chat：有效 finish_reason 才可完成；usage-only 尾块不改变终态；工具 ID/name/arguments 验证后交付。拒绝、截断与结构错误不得转成普通成功。
- Responses：JSON 仅 completed/incomplete 可完成；failed/error 显式失败，queued/in_progress/cancelled/缺失/未知状态均不视为同步成功。SSE completed/incomplete 是终态；保留 incomplete_details，max_output_tokens→length、content_filter→content_filter、未知原因→model_stream_invalid。参数按 item_id，缺失时按 output_index 关联，call_id 用于执行/结果关联。done-only 参数与 delta 不重复追加，坏/歧义调用失败。
- Anthropic：保留初始 input，delta 有内容时使用聚合参数；跟踪 content_block_stop，只允许闭合块成为候选调用；缺 stop reason、开放工具均失败。end_turn/stop_sequence、tool_use、max_tokens/model_context_window_exceeded、refusal 映射清楚；未知 stop reason 失败。message_stop 本身不足以使未闭合调用有效。
- 所有协议：有效未知扩展事件可忽略，坏 JSON 不跳过；第一终态后不得拼接新内容或执行后续工具，流/body 始终清理。只在模型请求已完整归一成功且非过滤/截断时执行工具，防止工具存在绕过 CompletionPolicy。

## 用量

按协议解释已有 usage 字段，不改变用户设置。Responses/Chat total 缺失时为 input+output，cache_read 是 input 子集；Anthropic 普通 input 与 cache_read/cache_creation 相加后再加 output。累计 usage 更新采用最新快照/对应字段合并，不累加每个 SSE 快照。total 有效时尊重供应商总值；负数、非数值、溢出/不合理字段显式验证，不能静默增加预算或抛出原始解析异常。已固定为 0..2**53-1 的 JSON 整数（不接受布尔/字符串/分数），相关无效值回归覆盖。

## 验收矩阵

| 场景 | 覆盖与断言 |
| --- | --- |
| 三协议×流式/非流式正常、工具、拒绝、截断 | 文本/调用一致、一次终态、过滤和截断不执行工具 |
| Responses failed 有/无 message、有/无 output；HTTP 200 error | Runtime 失败、无正常 done、平台 Run 非 completed |
| EOF/DONE/未知状态/坏 JSON | 部分文本可见、失败明确、调用数不增加、流关闭 |
| 工具闭合、零参数、缺 ID、稀疏索引、交错参数、done-only | 不串调用、不漏合法调用、不执行开放/歧义调用 |
| 400/401/403/404/408/422/429/500/502/503/504 | 稳定码与次数匹配，供应商秘密不泄漏 |
| 网络失败/部分流、Retry-After 两形式/越界/取消 | 仅预输出允许恢复，有界且可取消，已执行工具不重放 |
| input/cache/output/null/0/缺 total/重复 usage | 协议口径准确，Responses 100+20 cached40 为120，Anthropic 100+40+10+55为205 |
| worker/平台集成 | 失败不 completed、无未授权工具执行、事件重放不触发请求 |

上游 Go 测试需有 Go 环境后执行；本环境缺失则清楚保留未验证。Nexus 模拟协议、SQLite 和真实供应商分别记录证据。
