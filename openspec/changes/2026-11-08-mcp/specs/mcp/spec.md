# 规格：MCP

来源：`openspec/changes/2026-11-08-mcp`（待确认，确认并实施后归档）。

## 需求

### R1 MCP 服务与连接
- 一个 MCP 服务属于一个租户，名字在租户内唯一（1–64 字符，小写字母/数字/连字符）。
- 连接参数支持两种传输：`stdio`（`command`、`args`、`env`）与 `streamable_http`（`url`、`headers`）。
- 凭据不落明文：`headers` 与 `env` 中的秘密值以 `credential_references` 引用（引用 ID + 键名），运行时解析；解析失败时服务不可用并返回稳定错误码。
- 连接参数校验拒绝：未知传输、缺必要键、URL 非 http/https、命令为空、headers/env 含非字符串值、引用指向不存在或非本租户的凭据。
- 服务可启用 / 停用；停用后工具不在目录中出现，调用时授权拒绝（`mcp_service_disabled`）。
- 管理员（`tools:manage`）可增删改；所有活跃成员可读列表。

### R2 发现与按工具启用
- 连接服务后 `list_tools` 发现工具，发现超时 30 秒，失败重试一次（HTTP 传输断开重连；stdio 不重试）。
- 发现的工具默认**全部禁用**；管理员在 `enabled_tools` 白名单里逐个启用；白名单里不存在或不属于该服务的名字被拒绝。
- 工具目录带状态（`loading` / `ready` / `error`），错误原因可读；未 `ready` 的工具不注册。
- 停用服务、删除服务、移除启用白名单后，下一次调用即拒绝（执行时复核目录，不信任之前的定义）。

### R3 工具缓存与指纹
- 按（租户、服务）缓存工具定义（名字、描述、输入 schema、readOnlyHint）。
- 指纹取自连接参数（transport、url、headers 键与引用 ID、command、args、env 键与引用 ID），任何一项变化即失效并重新发现；秘密值不进入缓存与指纹。
- 缓存条目不含凭据明文，不落 Run 快照、事件、日志或异常。

### R4 注册名与外部前缀
- 注册名 `mcp_{sanitize(服务名)}_{sanitize(工具名)}_{sha256(server_id \0 tool_name) 的前 8 位十六进制}`，总长截断到工具名长度上限；同名先注册者保留。
- 工具描述带外部来源前缀（如 `[MCP 服务 "name" (external)]`），以降低间接提示注入风险。
- 输入 schema 为空或缺失时使用空对象 schema。

### R5 风险只升不降
- MCP 工具声明风险：仅 `readOnlyHint` 为真才降为 `read`，否则 `write`（MCP 默认 `destructiveHint` 为真，避免把未标注工具当成只读）。
- 每个（租户、服务、工具）可存显式风险与「曾观察到的最高声明」；生效风险 = `显式设置 > 曾观察最高声明 > 当前声明`；服务端自行降级时标记 `pending_downgrade`，须工作区显式确认才生效。
- 显式风险可额外置 `require_approval`（该工具每次审批）。
- 策略读取失败默认 fail-close：临时按 `write` 且需要审批，不静默放行。
- 生效风险映射到 `ToolDefinition.risk`；`require_approval` 映射到 `ToolDefinition.requires_approval`。

### R6 执行与错误分类
- 每次执行前重新读取服务配置、启用白名单、风险策略，任一步失败返回 `mcp_unavailable`，不调用外部服务。
- `McpError`（服务端拒绝调用）返回「参数被拒绝，请修正类型、必填字段与嵌套后重试」的提示；输出 schema 校验失败返回「参数已被接受，不要改参数重试」。
- 工具结果带外部数据前缀，并照常经过注入扫描、外置与头尾截断（复用网关管线）。
- 调用超时按服务配置与网关超时取较长者；取消按现有 `CancellationTokenPort` 语义。

### R7 schema 清洗与渐进加载
- 输入 schema 按供应商清洗（复用 `nexus_core.schema.sanitize`），空值剔除（可选字段不推 null），参数名非法时按既有规则改名并在执行前 `restore`。
- MCP 工具 `source='mcp'`、`group='mcp'`、`deferrable=True`；schema 估算超阈值时经 `tool_search` / `tool_describe` / `tool_call` 渐进加载，`tool_call` 展开后走完整网关管线。

### R8 分组门控
- `nexus_core.native.tool_groups` 新增 `mcp` 组，默认关闭；MCP 工具只有在该组可用且智能体开启时才出现在 Run 的工具块里，直接调用也返回 `tool_authorization_denied`。
- MCP 服务经 `agent_resource_bindings`（kind `mcp_service`）绑定到智能体；绑定与服务启用、工具白名单共同决定可见工具。

### R9 MCP 服务端与运行令牌
- 平台以 MCP 协议暴露某次 Run 已授权的工具（`tools/list`、`tools/call`），供 Codex / Claude Code 等外部 Runtime 调用。
- 运行令牌：短时、单 Run、与 Run 生命周期一致；Run 结束 / 取消 / 撤销即失效；令牌本身只作索引，不在日志、事件中记录明文。
- 每次 `tools/list` 返回该 Run 当前授权可见的定义（过滤 `deny`）；每次 `tools/call` 走完整网关管线复核权限，不信任快照、模型参数或技能声明。
- 鉴权失败、令牌过期、Run 不存在或非运行态分别返回稳定的协议级错误，不泄漏是否存在资源。

### R10 审计与测试
- MCP 服务增删改、工具启用变更、风险策略变更写审计；每次 MCP 工具调用复用 `ToolAccessPort` 的调用与审计记录。
- 测试覆盖：连接参数校验与指纹失效、按工具启用、风险只升不降与降级确认、执行时复核、`McpError` / 输出 schema 错误分类、注册名哈希防撞、渐进加载、服务端运行令牌生命周期与撤权后拒绝。
