# WeKnora 请求、流聚合与终态审查

2026-10-25；固定提交 `e1f9a6166a593a4804a2f99f1d942919c9cc8ea7`。根 MIT、Copyright 2026 Tencent，第三方例外仍按根许可证与实际依赖核对。本批没有复制实现。

全文阅读并核对哈希：api/endpoint.go、endpoint_test.go、sse.go、sse_test.go、usage.go、stream_assembler.go、stream_assembler_test.go，三协议 client.go，openaicompletions/stream_tool_index_test.go。对三协议 request.go、Responses/Anthropic 综合测试与 Completions golden_test.go 做请求生成和终态相关分支核对；这些文件仍只记定点阅读，不宣称全部测试映射完成。路径均相对 internal/models/。

## 当前批次实现

上文审查对应的三个复现缺口已在用户确认后的局部修复中覆盖，证据见 [验收记录](../../openspec/changes/model-terminal-consistency/verification.md)。本文复现段保留为原审查证据，不等同当前实现状态；完整模型迁移仍未完成。

## 请求与生命周期

Endpoint 负责 JSON 编码、认证、自定义 header、URL SSRF 校验、Session ID 与固定 User-Agent；静态模型 header 不能覆盖本次会话身份。Do 将发送失败包装为 TransportError，非 2xx 保留 HTTPError/status/header 和最多 1 MiB 正文，并关闭 body。PostJSON 将超大响应、解码失败和读取中断区分，只有读取中断包装为 TransportError。Retry-After 支持数字秒和 HTTP 日期。

三协议 Chat/ChatStream 均建立有界 context；流由 goroutine 驱动，退出时关闭 body/channel、取消 context、关闭可选 dumper。本层不是统一自动重试循环；仅在识别为不支持图片时尝试去图片重发。日志/dumper 可包含请求与响应内容，Nexus 不直接复制原始正文外显或共享日志方式。

请求生成按协议配置决定采样、token 上限字段、tool choice、parallel 标志、thinking、cache 和额外 body。Responses 抽取 system 为 instructions，保留独立 item ID 与 call ID、reasoning 原始 metadata；Anthropic 分块保留已签名 thinking 与 redacted thinking，避免将改写后的可读摘要当原签名内容回传。此批不将这些能力收进局部错误修复后声称全部迁移。

## SSE 和共享聚合

SSEReader 按行处理 data:，接受无空格、CRLF、带尾空格的 DONE；跳过 event/id/comment，单行上限 1 MiB。它不是通用多行 SSE event 拼接器。

StreamAssembler 按厂商索引排序工具，支持非零起点/稀疏索引；名称重复全文不再次拼接，参数累加。提供稳定名称后的早期工具通知、thinking tool 字段提取、沙箱文件进度、reasoning metadata 和 usage。发送检测 context 取消，消费者离开后保持 aborted，协议循环据此停止读取。

Process 和 End 都可能发 Done=true；上游 Done 既表示内容段/回合收尾，也携带最终 usage，不等同 Nexus 的单次 ModelChunk(done)。Nexus 应保持可观察结果与顺序，通过一次终态归一表达，不照搬重复 Run 终态事件。

EndAtEOF 在缺 finish reason 时标 incomplete；Fail 发 error/incomplete 并保留已聚合工具与 usage。保留在错误事件里的工具是诊断数据，不应据此推断平台可执行。

## 三协议终态和工具完整性

| 协议 | 正常与异常分支 | 上游例外与兼容边界 |
| --- | --- | --- |
| Chat | 普通 JSON 检查 error、choices、工具解码；流坏 JSON/坏工具立即失败；EOF 无 finish 标 incomplete | DONE 哨兵直接 End，可无 finish_reason；现有测试明确接受。Nexus SDK 目前更严格，这项差异必须公开记录 |
| Responses | JSON status=failed 即使无 error.message 也失败；SSE failed/error 立即 Fail；completed/incomplete 提交 usage/终态 | 没有协议终态的 EOF/DONE 均 incomplete；工具存在时 finishReason 优先 tool_calls，可能盖过 incomplete 原因，Nexus 拟保留截断优先级 |
| Anthropic | 分 index 聚合工具输入并记录 closed；只返回闭合调用，未闭合时 incomplete；零参数工具保留 initial input | EOF 若已有 stop reason 且无开放工具，可由 finish 完成；没有额外硬性 message_stop 门禁。refusal→content_filter、max_tokens/context_window→length |

Responses 参数按 item_id 关联，缺失时用 output_index；output_item.done 为无 delta 的调用补参数，避免覆盖/重复追加已有片段。坏 item 事件即失败，末尾 response.output 中无法解析的 reasoning 回退允许忽略。Anthropic message_start 与 message_delta 分开合并 input/cache 与累计 output，不将 usage 增量当成多次计费。

## 用量

Responses input 已含 cached，total 缺失时 input+output，cached 只作分项。Messages input 为普通 input+cache read+cache write，再加 output。Chat 支持多个缓存字段并有明确优先级，区分 reported/unreported/unsupported。Nexus 当前没有全部状态/字段对等契约，局部修复先保证已有总量与分项准确，其他缺口保留。

## 原测试映射与本地复现

已全文阅读的公共测试覆盖请求身份、Retry-After、SSE 哨兵、取消发送、thinking 交接、工具稀疏索引，以及无索引工具的分离与续片。综合协议测试定点核对 failed、缺终态、坏 JSON/工具、Responses 缺 item ID、Anthropic 开放工具、零参数、累计 usage 与 stop reason。

本环境 PATH 无 Go 可执行文件，未运行 WeKnora Go 测试。这是环境阻碍，不是测试通过，也不能以 Nexus 模拟响应代替上游验收。

本批用 Nexus StructuredModel + httpx.MockTransport 复现：Anthropic 未发 content_block_stop 但已发 message_delta/tool_use 与 message_stop，仍产出 tool_call 和 done/tool_calls；说明适配器未验证工具块闭合，没有实际执行工具。直接调用已有 usage_chunk，Responses input=100/output=20/cached=40 且缺 total 时得到 160，正确协议口径应为 120。此前非流式 Responses failed→done/stop 的复现继续有效。

只记录本次执行的模拟与静态证据，本次没有重跑程序回归或请求真实供应商。来源哈希、清单一致性和文档检查随本次交付核验。

## 局部修复与剩余范围

[模型错误与终态一致性提案](../../openspec/changes/model-terminal-consistency/proposal.md)定义修复范围、冲突决策与验收矩阵。完整模型历史/签名、供应商配置、缓存治理、多模态降级、早期进度与上游其余文件仍保留在审查/迁移清单，不因本批提案而消失。
