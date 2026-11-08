# 任务：MCP

- [ ] 0. 准备与补读
  - [ ] 0.1 加入官方 `mcp` Python SDK **2.x**（pin `mcp>=2.3,<3`，不引入 `langchain-mcp-adapters`）到 `packages/mcp` 依赖与 `uv.lock`；建立 `nexus_mcp._sdk` 适配层（唯一允许 `import mcp.*` 的模块）并核对 `ClientSession` / `stdio_client` / `streamable_http_client` / `sse_client` / `MCPServer`（2.x 改名）API 与 `httpx2` 边界。
  - [ ] 0.2 补读 WeKnora `mcp_catalog.go` / `mcp_schema.go` / `mcp_call_guard.go` / `client.go` / `sse_connection.go` / `mcp_oauth.go`、Octop `custom_mcp.py`、deer-flow `session_pool.py` / `lifecycle.py` / `headers.py` / `tools.py` / `cache.py` / `interceptors.py` / `oauth.py` / `oauth_store.py`、hermes `mcp_tool_transport.py`（stdio 进程卫生与 SSE/HTTP 连接工厂）与 `mcp_oauth_manager.py` / `mcp_oauth_provider.py`（OAuth PKCE/动态注册）的完整行为与测试。

## 1. 客户端与平台服务
- [ ] 1.1 持久化模型与迁移：`mcp_services`、`mcp_service_tools`（含 `config_epoch`）、`mcp_tool_approvals`、`mcp_oauth_clients`、`mcp_oauth_tokens`、`mcp_run_tokens`；空库 / 已有库 / 重复执行验证。
- [ ] 1.2 `nexus_mcp.client`：连接参数校验（含 header 非法值校验与大小写不敏感替换）、`fingerprint`、`config_epoch` 生命周期账本、`discover`（30s 超时、HTTP 重连一次、stdio 不重试）、持久会话池（anyio 所有权约束 + LRU 回收）、`call` 与 `McpError` / 输出 schema 错误分类；传输三选一：stdio（子进程 + 进程卫生）、streamable HTTP、SSE（`sse_read_timeout` 分离事件间隔与建连预算，TLS / 响应体上限 / 同源重定向按 WeKnora/hermes 收紧）。
- [ ] 1.3 `nexus_platform.mcp.service`：服务 CRUD（`tools:manage`）、工具发现与指纹缓存、按工具启用白名单、停用 / 删除后执行时复核。
- [ ] 1.4 风险策略：声明风险解析（`readOnlyHint` → `read`，否则 `write`）、`observe_declared_risk` 只升、显式风险 + `require_approval`、`pending_downgrade` 需确认、读取失败 fail-close。
- [ ] 1.5 `nexus_mcp.gateway`：`visible_definitions` → `ToolDefinition`（`source='mcp'`、`group='mcp'`、`deferrable=True`、外部前缀描述、schema 清洗、工具名加载边界清洗）；注册名哈希防撞；执行器执行前复核目录 / 白名单 / 风险后再 `client.call`。
- [ ] 1.6 `nexus_core.native.tool_groups` 增加 `mcp` 组（默认关闭），接入 `preparation.py` / `tool_gates.py`。
- [ ] 1.7 管理 API：`/api/v1/tenants/{id}/mcp-services` 的 CRUD、`discover`、`enabled-tools`；`/agent-tools` 能力目录补 MCP 分组（只读 + 管理员开关）。
- [ ] 1.8 OAuth 客户端：授权码流（RFC 9728 动态客户端注册 + PKCE），令牌按（租户、主体、服务）作用域存储与自动刷新；401 恰好一次 refresh + 一次重试；凭据优先级「请求级 > 用户级 > 服务级」；保留静态 header/env + `credential_references` 路径。

## 2. MCP 服务端
- [ ] 2.1 `mcp_run_tokens`：签发（单 Run、短时、可撤销）、哈希存储、解析与过期判定。
- [ ] 2.2 `nexus_mcp.server`（FastMCP）：`tools/list` 返回 Run 当前授权定义，`tools/call` 走 `AuthorizedToolGateway.execute` 完整管线。
- [ ] 2.3 API 挂载 `/mcp/runs/{token}`，Bearer 鉴权映射到 Run，提前于全局 Auth；稳定协议级错误不泄漏资源存在性。

## 3. 测试与文档
- [ ] 3.1 单元测试：连接参数校验（含 header 非法值）与指纹失效、`config_epoch` 变更重建绑定、按工具启用、风险只升不降 + 降级确认、执行时复核、`McpError` / 输出 schema 分类、注册名哈希防撞、外部工具名清洗、OAuth 令牌作用域与刷新、401 单次重试。
- [ ] 3.2 集成测试：假 MCP 服务（stdio + HTTP + SSE）发现 / 调用 / 撤权后拒绝；服务端运行令牌生命周期（签发 / 调用 / 撤销 / 过期）；OAuth 授权码流端到端（动态注册 → 授权 → 令牌刷新）。
- [ ] 3.3 文档：`docs/architecture.md` 2.7、`docs/roadmap.md` 第 7 步、`packages/mcp` 的 `README.md` / `docs/{requirements,design}.md`。
- [ ] 3.4 全量 `uv run --locked pytest` 与锁定前端类型检查 / 构建（若前端有改动）。

## 4. 前端（决定 5）
- [ ] 4.1 工具箱 MCP 标签按 WeKnora 实现最小可用：服务列表 / 创建与编辑（transport、url、command/args/env、headers 引用）、发现工具、`enabled_tools` 启停。
- [ ] 4.2 接入后端 `/api/v1/tenants/{id}/mcp-services` 路由与 `tools:manage` 权限；中英文文案一次加齐（vue-i18n）。
- [ ] 4.3 浏览器测试：MCP 服务创建、发现、启用一个工具、停用服务。
