# 模型协议、历史与故障转移审查

2026-10-25。GenericAgent 固定为 `a9a36b4b219593369de01c3e5973e56ac02e568b`，WeKnora 固定为 `e1f9a6166a593a4804a2f99f1d942919c9cc8ea7`。全文阅读 GA `llmcore.py`（1,270 行）、WK `internal/models/api/retry.go` 与 `retry_test.go`，并核对来源索引哈希。两项目根许可证为 MIT，分别归属 2025 lsdefine 与 2026 Tencent；WK 根许可证另列第三方例外，实际迁移依赖仍须逐项核对。本批只写分析，没有复制上游实现。

定点阅读 GA 桌面模型切换测试，以及 Nexus models 的 factory、routing、retry、tool_protocol、protocols/structured、openai_compatible 和对应回归测试。WK 其余模型协议、HTTP Endpoint 和 stream assembler 尚未在本批完整审查，不将本批结论推广为整个模型模块完成。

## 当前实现说明

本文缺口表为修复前审查基线。用户已确认并完成“模型错误与终态一致性”局部实现；当前修复及验证以 [批次记录](../../openspec/changes/archive/2026-10-25-model-terminal-consistency/verification.md)为准，不将下列全部差异当作仍未修复或完整迁移已完成。

## 配置、连接与会话基础

- GA MyKeys 优先查找并执行 mykey Python 源码，否则读取 mykey.json；JSON 可含 remote_url 并发出远程配置请求。加载前后比对本地 mtime_ns，reload 普通异常保留旧快照，成功更新单调版本；Python 加载中的 BaseException 清理 sys.modules 后继续抛出，不全部被 reload 吞掉。
- snapshot 返回共享数据对象而非深拷贝。远端 JSON 的独立变化不会在本地 mtime 不变时自动触发重新读取。配置执行、远程地址与全局缓存不能直接作为平台多租户配置方案。
- 导入时全局包装 urllib3 HTTPConnection.request，按线程登记活动 socket，供外部 abort 关闭；本文件没有完整的登记清理生命周期。关闭 TLS 警告不等于禁用校验，实际 verify 默认为 true。
- BaseSession 的上下文、压缩间隔和工具输出倍率按 context_win 与 DeepSeek 特例计算；支持 prefix 保留、extra system 文本/文件、代理、TLS、重试、流式、thinking、reasoning、service tier、usage 和 user agent。connect_timeout 实际读取 cfg.timeout，而配置向导写 connect_timeout，存在字段不一致。
- api_mode 将 response/responses 归一为 responses，其余回退 chat_completions。reasoning/service/thinking 通过枚举过滤；Claude enabled thinking 无 budget 时仅警告，xhigh 映射 max。这些默认值是锁定源码行为，不代表供应商当前推荐值。
- URL 支持末尾 `$` 表示完整地址，已带路径不再追加，否则识别 /v数字/ 后决定是否插入 v1。Nexus 当前使用显式 base_url 与协议路径，不能宣称支持同样的 URL 语法。

## 历史压缩与消息修复

- compress_history_tags 的调用计数存在函数属性中，跨会话共享；定期压缩较老消息，保护近期尾部。history/key_info/earlier_context/global_memory 标签替换为索引占位，thinking/tool_use/tool_result 内容按首尾裁剪；原列表原地更新。
- trim 以 context_win×3 的字符成本近似容量，先常规压缩，再强制保护最近四条压缩，仍超量时按 user 边界删除旧片段并尽量保留尾部九条；不是 tokenizer 计量。首个残留 user 的 tool_result 转成普通文本，前缀 assistant 的悬空 tool_use 被移除并插入过渡占位。
- _fix_messages 合并相邻角色、丢弃非 user/assistant 和开头 assistant，去重有 ID 的 tool_use，按前一 assistant 调用顺序排列 tool_result，缺失结果补 `(error)`，孤立/重复结果降为文本，空内容补 `.`。
- Claude 历史删除无 signature 的 thinking；DeepSeek 缺 thinking 时补占位。Claude→OAI 转换保留工具 ID、结果与 base64 图片；Responses 转换映射 system→developer、图像、function_call/output 并为缺失 ID 提供回退。显式 tool_call_id 不消费 pending 队列，混用显式与缺失 ID 的情况需补测试。
- NativeToolClient 把输入合成一条 user 消息，为未回传的 pending tool ID 补空结果；过滤合并内容时只保留 text 非空的块，原代码可能丢弃图像块。ask 的历史写入排除单块 `!!!Error:`，但其他错误/截断标记不一定排除。omit_thinking 仅改变历史保留。

## 三种协议与终态

| 路径 | 真实行为与边界 | 必须保留的验收点 |
| --- | --- | --- |
| Claude SSE | text/thinking/signature/tool 参数分片；坏工具 JSON 放 `_raw`；识别 message_stop/stop_reason；max_tokens、refusal、缺终态插入文本警告；HTTP 200 overload 文本可转 ConnectionError | 多块/坏 JSON、签名、截断/拒绝/断流、警告位置与工具安全 |
| Claude JSON | refusal 提前返回错误文本；否则记录 usage、text 可见、thinking 不直接输出、返回原块 | JSON 与 SSE 的可见输出差异、usage 与拒绝 |
| Responses SSE | 按 output_index 聚合 function call；delta 与 done 文本回退；reasoning 单独保存；completed/incomplete/failed/error 分支不同 | done-only 文本、参数交错、缺 ID、失败与截断、缺终态 |
| Responses JSON | 提取 message/reasoning/function；failed 转错误，incomplete 无文本时补截断标记 | 不可将 failed 归一成功；有工具但无文本时的截断差异 |
| Chat SSE/JSON | reasoning/text、工具分片和 usage；SSE 无名片段可能拼到最后索引；非流式只读首个 choice | 缺 index、多个调用、空 choices、终态和 usage |

_try_parse_tool_args 会拆相邻 `{…}{…}` 并给 ID 加后缀；失败保留 `_raw`，成功 JSON 不一定是 dict。SSE 与非流式工具 JSON 恢复不完全相同。上游 Chat SSE 不严格检查 finish_reason；Responses SSE 没有通用“必须收到终态”门禁，不能用旧 MockResponse 默认 end_turn 证明传输完整。

usage 写进全局 STATS，null/非法数字回退 0；Messages input 合并普通、cache creation/read，Chat 与 Responses 使用各自字段。TTFT 以首条非空 SSE 行计，可能早于可见文本；tps 用输出 token 与解码区间计算。全局状态可能被并发请求覆盖，必须适配成 Run/请求级使用量。

## 提示词、工具协议和日志

普通 ToolClient 使用文本协议，深拷贝 schema，并将 file_write.content 移至正文标签。工具说明在 schema 未变时省略，按累计字符估算和循环周期重新发送；包含中英文摘要/行动指令。NativeToolClient 使用 native schema，并独立组合 system 与行动规范。

文本解析先尝试末尾 JSON 数组和 XML tool_use/tool_call；普通 ToolClient 再尝试缺闭合标签、裸 JSON、function/tool 与 args/params/parameters 别名。tryparse 有去代码围栏、删最后字符、截到最后右花括号等宽松恢复。无法解析时可能生成 bad_json，也有吞掉异常的分支。Nexus 的显式开关、严格 JSON/对象校验和 native 优先去重不是这些路径的完整等价实现。

thinking-only 响应会将首行截为 summary 文本。原提示、响应和部分调试内容写到 temp/model_responses；log_path=False 可禁用。原始内容、宿主路径和身份伪装 header/system 不可静默照搬：是否保留、替换或暂缓须在提案中说明，凭据与用户内容外发要经过平台边界。

## 重试与 Mixin 真实行为

GA 传输层尝试 max_retries+1 次；可重试 HTTP 集合包含 408/409/425/429、常见 5xx 与代理状态。Retry-After 仅按数字秒读取，超过 cap 直接停止；其他延迟至少 0.5 秒、指数上限 30 秒。等待每 0.2 秒检查 should_stop，活动 response/socket 供取消使用。

空返回且无任何 yield 转 ConnectionError；即便 yield 空字符串也算 streamed。Timeout/ConnectionError/ChunkedEncodingError 在已有输出后仍可能重新发送请求，已输出内容未撤回；其他异常以错误文本结束。HTTP 错误正文最多 500 字进入错误文本，没有平台秘密过滤。部分输出后重试与 Nexus 禁止重拼流存在明确冲突。

Mixin 按索引或别名选节点，要求全部 Native 或全部非 Native，浅拷贝节点并将其传输重试归零；facade 深拷贝主节点历史，共享 system/tools 与 facade lock。允许 transport override 同步所有节点，节点专有字段只读；按主节点 ask 实现驱动 facade，节点 raw_ask 保持各自协议。类型解析主要依据配置变量名，而非 cfg.type。

轮转从 sticky 节点开始，最多 facade retries+1；绕回 base 才按 1.5 倍轮数退避，普通 time.sleep 不检查停止。错误判断依赖最后 chunk 的 `!!!Error:` / `[Error:` 前缀；开头错误可被隐藏，空返回/无 chunk 不一定认作失败。部分中断标记通常保留当前输出，可能为下一次选择备用节点；超过 spring_back 才回主节点。异常直接抛出没有统一 facade catch/finally，不能等同 typed RuntimeFault。

## WeKnora 重试及原测试

WK withRetry **只重试 TransportError**，包括读取响应中断；完整非 2xx 和完整但不可解码的响应不重试。BaseDelay 每次翻倍、MaxDelay 截断、零延迟有效；退避等待监听 context.Done。首次 send 前没有本函数独立的 ctx 检查，取消依赖请求层；负 MaxRetries 也没有显式校验。

已阅读八个测试：上游不可达仍返回错误、首次传输失败后成功且 header 保持、拒绝不重试、不可解码不重试、context 取消、指数与上限、响应体半途断开重试、read response 的 TransportError.Op。未运行 Go 测试，Endpoint 实现与其他重试调用方仍待核对。此 helper 是 JSON 请求语义，不能推广成所有 Agent 流/工具的重试规则。

## Nexus 对照、复现与修复批次

当前代码已存在三协议 adapter、text tools、RetryModel、RoutedModel，不能继续笼统描述为“全部缺失”。但仍有以下确定差异与待验证点：

- RetryModel 仅对三类 typed fault 重试，输出 text/tool_call/done 后不重试，指数可取消异步等待；RoutedModel 每轮各节点最多一次，后续请求 sticky/spring-back。无 GA 的 Retry-After、完整状态集合、Mixin transport override 或轮转策略等价证据。WK 拒绝不重试与 GA 可重试 HTTP 的冲突需按错误类别明确选择，不能统称“已按原逻辑迁移”。
- StructuredModel 非流式 Responses 仅把 incomplete 转 max_tokens，其他 status 一律 stop。本批用 httpx.MockTransport 返回 HTTP 200、status=failed、空 output，实际得到 `done/stop`，确认错误终态归一缺口；未请求外网、未调用真实模型。
- StructuredModel 对所有非 429 HTTP 错误使用 provider_unavailable；Chat APIStatusError 也多归此码，叠加 RetryModel 后可能重复发送不可重试拒绝。需区分身份/参数/配额/暂时故障与供应商原始内容脱敏。
- Responses done-only 文本回退、完整 failed/incomplete_details、缺工具字段、thinking/signature/history、多模态、cache marker、工具 JSON 拆分/宽松文本恢复和各模型请求特例没有完整实现/测试证据。
- Structured usage 默认 total 将 cached 再计入 input/output，Responses 已包含 cached 的 input_tokens 可能被重复计数；需按协议分别验证。Chat 非流式 usage 未投影 cache_read；详细使用量不能仅靠总 token 正常路径通过验收。
- SDK Chat 对 finish_reason、工具索引/ID、字符预算和流关闭有额外约束；StructuredModel 的 done/stop 边界与它不同。应补三协议统一的终态/失败/取消差分矩阵，而非把宽松上游和严格当前实现合称等价。

建议首个修复批次为“模型错误与终态一致性”：覆盖非流式 failed、HTTP 错误分类、终态缺失/截断、部分流禁止重发与 usage 计数；先完善迁移提案的行为决策和测试矩阵，按仓库规则确认后改 Runtime，不在本次静态审查中悄悄修复。

## 验证证据与未完成项

本批运行 Nexus 的协议流式/非流式、重试/切换不重放部分流、工具分片/错误脱敏、deadline/坏流/context 错误用例；命令为 `uv run --locked pytest -q` 后指定 `tests/test_native_parity.py::test_protocol_adapters_streaming_and_nonstream`、`tests/test_native_parity.py::test_retry_and_fallback_never_replay_a_partial_stream`、`tests/test_native_runtime.py::test_provider_fragmented_calls_usage_and_error_redaction`、`tests/test_native_runtime.py::test_provider_deadline_invalid_stream_and_context_errors`；结果 6 passed、无跳过，2.91 秒，有一条 Starlette/httpx 弃用警告。它们主要使用模拟响应，不能证明真实供应商兼容或完整源码对齐。另有上文 MockTransport failed 复现，作为缺陷证据而非通过验收。

上游桌面 test_bridge_model_switch 是 FakeAgent/simulate_set_session_model 的 13 项模拟契约，不直接运行 llmcore/Mixin；全仓 *test*.py 定点检索未找到 MixinSession/_stream_with_retry/两个 SSE parser/compress_history_tags 直接引用。不把无命中视为不存在间接覆盖，也不把模型热切换测试算作故障转移证明。

未完成：WK 三协议与 Endpoint/assembler/并发封装完整审查、全部原测试映射、GA 与 Nexus 差分测试、模型参数前端与持久化字段逐项对照、真实模型和 PostgreSQL 环境验收。沙箱及六项执行工具暂缓保持不变。
