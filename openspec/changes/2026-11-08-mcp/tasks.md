# 任务：MCP

- [x] 0. 准备与补读
  - [x] 0.1 加入官方 `mcp` Python SDK **2.x**（pin `mcp>=2.3,<3`，不引入 `langchain-mcp-adapters`）到 `packages/mcp` 依赖与 `uv.lock`；建立 `nexus_mcp._sdk` 适配层（唯一允许 `import mcp.*` 的模块）并核对 `ClientSession` / `stdio_client` / `streamable_http_client` / `sse_client` / `MCPServer`（2.x 改名）API 与 `httpx2` 边界。
  - [x] 0.2 补读 WeKnora `mcp_catalog.go` / `mcp_schema.go` / `mcp_call_guard.go` / `client.go` / `sse_connection.go` / `mcp_oauth.go`、Octop `custom_mcp.py`、deer-flow `session_pool.py` / `lifecycle.py` / `headers.py` / `tools.py` / `cache.py` / `interceptors.py` / `oauth.py` / `oauth_store.py`、hermes `mcp_tool_transport.py`（stdio 进程卫生与 SSE/HTTP 连接工厂）与 `mcp_oauth_manager.py` / `mcp_oauth_provider.py`（OAuth PKCE/动态注册）的完整行为与测试。

## 1. 客户端与平台服务
- [x] 1.1 持久化模型与迁移：`mcp_services`、`mcp_service_tools`（含 `config_epoch`）、`mcp_tool_approvals`、`mcp_oauth_clients`、`mcp_oauth_tokens`、`mcp_run_tokens`；空库 / 已有库 / 重复执行验证。
- [x] 1.2 `nexus_mcp.client`：连接参数校验（含 header 非法值校验与大小写不敏感替换）、`fingerprint`、`config_epoch` 生命周期账本、`discover`（30s 超时、HTTP 重连一次、stdio 不重试）、持久会话池（anyio 所有权约束 + LRU 回收）、`call` 与 `McpError` / 输出 schema 错误分类；传输三选一：stdio（子进程 + 进程卫生）、streamable HTTP、SSE（`sse_read_timeout` 分离事件间隔与建连预算，TLS / 响应体上限 / 同源重定向按 WeKnora/hermes 收紧）。
- [x] 1.3 `nexus_platform.mcp.service`：服务 CRUD（`tools:manage`）、工具发现与指纹缓存、按工具启用白名单、停用 / 删除后执行时复核。
- [x] 1.4 风险策略：声明风险解析（`readOnlyHint` → `read`，否则 `write`）、`observe_declared_risk` 只升、显式风险 + `require_approval`、`pending_downgrade` 需确认、读取失败 fail-close。
- [x] 1.5 `nexus_mcp.gateway`：`visible_definitions` → `ToolDefinition`（`source='mcp'`、`group='mcp'`、`deferrable=True`、外部前缀描述、schema 清洗、工具名加载边界清洗）；注册名哈希防撞；执行器执行前复核目录 / 白名单 / 风险后再 `client.call`。
- [x] 1.6 `nexus_core.native.tool_groups` 增加 `mcp` 组（默认关闭），接入 `preparation.py` / `tool_gates.py`；MCP 服务经 `agent_resource_bindings`（kind `mcp_service`）绑定，Run 快照写入 `mcp_service_ids`，worker 把已启用 MCP 工具注册进 `AuthorizedToolGateway`（`apps/worker/nexus_worker/mcp_tools.py`）。
- [x] 1.7 管理 API：`/api/v1/tenants/{id}/mcp-services` 的 CRUD、`discover`、`enabled-tools`；`/agent-tools` 能力目录补 MCP 分组（只读 + 管理员开关）。
- [x] 1.8 OAuth 客户端：授权码流（RFC 9728 动态客户端注册 + PKCE），令牌按（租户、主体、服务）作用域存储与自动刷新；401 恰好一次 refresh + 一次重试；凭据优先级「请求级 > 用户级 > 服务级」；保留静态 header/env + `credential_references` 路径。（`nexus_mcp.oauth` 协议层；`nexus_platform.mcp.oauth` 加密令牌/客户端与 state；管理接口 authorize-url / status / token 与公开回调；worker 与发现路径 401 单次重试。）

## 2. MCP 服务端（无状态 endpoint；2026-11-09 修订决定 2，废弃运行令牌）
- [ ] 2.1 撤销运行令牌：删除 `mcp_run_tokens` 表与迁移、`issue_run_token` / `resolve_run_token` / `revoke_run_token`、`RunMCPServer` 绑 Run 协议层，并将 3.2 的运行令牌用例改为 endpoint 令牌用例。
- [ ] 2.2 `mcp_endpoints` 持久化：endpoint 表（名称、工具白名单、KB 范围、`token_hash`、`enabled`、`last_used_at`）与迁移；空库 / 已有库 / 重复执行验证。
- [ ] 2.3 endpoint 长期令牌：签发 / 轮换 / 撤销，SHA-256 哈希存储、解析与撤销判定。
- [ ] 2.4 无状态工具面 + `EndpointMCPServer`：为知识检索 / web / skills / memory / conversations 只读工具提供平台服务的无状态入口（tenant + principal + KB 范围，不依赖 Run store）；`tools/list` 返回白名单内只读定义，`tools/call` 在 API 进程内直接调平台服务并复核作用域。
- [ ] 2.5 API 挂载 `/mcp/{endpoint_id}` + 鉴权中间件：Bearer → endpoint 作用域化 principal，提前于全局 Auth；稳定协议级错误不泄漏资源存在性。
- [ ] 2.6 管理 API `/api/v1/tenants/{id}/mcp-endpoints`：CRUD + 签发 / 轮换 / 撤销令牌。
- [ ] 2.7 文档同步：`docs/architecture.md` 2.7、`docs/roadmap.md` 第 7 步、`packages/mcp` 模块文档，把「运行令牌 + `/mcp/runs/{token}`」改为「endpoint 长期令牌 + 无状态只读工具面」。

## 3. 测试与文档
- [x] 3.1 单元测试：连接参数校验（含 header 非法值）与指纹失效、`config_epoch` 变更重建绑定、按工具启用、风险只升不降 + 降级确认、执行时复核、`McpError` / 输出 schema 分类、注册名哈希防撞、外部工具名清洗、OAuth 令牌作用域与刷新、401 单次重试。（`tests/test_mcp_client.py`、`tests/test_mcp_service.py`、`tests/test_mcp_oauth.py`：协议/元数据/令牌、加密 state 防篡改与过期、按主体隔离、惰性/强制刷新、授权被拒清理、回调重定向；401 的平台级单次刷新重试由 3.2 的端到端用例覆盖。）
- [x] 3.2 集成测试：假 MCP 服务（stdio + HTTP + SSE）发现 / 调用 / 撤权后拒绝；服务端运行令牌生命周期（签发 / 调用 / 撤销 / 过期）；OAuth 授权码流端到端（动态注册 → 授权 → 令牌刷新）。（`tests/test_mcp_integration.py`：真实 `MCPServer` 经 stdio 子进程 / streamable HTTP / SSE；停用服务后 `resolve_call` 拒绝；`RunMCPServer` 经协议 `tools/list` / `tools/call` 且运行令牌撤销后拒绝；假授权服务器 + 401 守卫完成注册、授权、换码、惰性刷新、401 强制刷新重试与 `invalid_grant` 撤权重授权。顺带修正：streamable HTTP 的 401 按响应状态观测（SDK 丢弃状态码）、发现工具的令牌解析移出目录事务。）
- [x] 3.3 文档：`docs/architecture.md` 2.7、`docs/roadmap.md` 第 7 步、`packages/mcp` 的 `README.md` / `docs/{requirements,design}.md`。
- [x] 3.4 全量 `uv run --locked pytest` 与锁定前端类型检查 / 构建（若前端有改动）。（后端全量 1628 passed / 1 skipped；前端无改动。）

## 4. 前端（决定 5）
- [x] 4.1 工具箱 MCP 标签按 WeKnora 实现最小可用：服务列表 / 创建与编辑（transport、url、command/args/env、headers 引用）、发现工具、`enabled_tools` 启停。
- [x] 4.2 接入后端 `/api/v1/tenants/{id}/mcp-services` 路由与 `tools:manage` 权限；中英文文案一次加齐（vue-i18n）。
- [x] 4.3 交互测试：MCP 服务创建、发现、启用一个工具、停用服务。（仓库无 Playwright，按现有 node:test 组件交互测试惯例实现于 `apps/web/src/views/toolbox/mcpInteractions.test.ts`，配合纯函数单测 `toolboxMcp.test.ts`。）
