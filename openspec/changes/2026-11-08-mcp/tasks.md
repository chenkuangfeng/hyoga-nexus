# 任务：MCP

- [ ] 0. 准备与补读
  - [ ] 0.1 确认官方 `mcp` Python SDK 版本并加入 `packages/mcp` 依赖与 `uv.lock`。
  - [ ] 0.2 补读 WeKnora `mcp_catalog.go` / `mcp_schema.go` / `mcp_call_guard.go`、Octop `custom_mcp.py`、deer-flow `session_pool.py` / `lifecycle.py` 的完整行为与测试。

## 1. 客户端与平台服务
- [ ] 1.1 持久化模型与迁移：`mcp_services`、`mcp_service_tools`、`mcp_tool_approvals`、`mcp_run_tokens`；空库 / 已有库 / 重复执行验证。
- [ ] 1.2 `nexus_mcp.client`：连接参数校验、`fingerprint`、`discover`（30s 超时、HTTP 重连一次、stdio 不重试）、会话池与回收、`call` 与 `McpError` / 输出 schema 错误分类。
- [ ] 1.3 `nexus_platform.mcp.service`：服务 CRUD（`tools:manage`）、工具发现与指纹缓存、按工具启用白名单、停用 / 删除后执行时复核。
- [ ] 1.4 风险策略：声明风险解析（`readOnlyHint` → `read`，否则 `write`）、`observe_declared_risk` 只升、显式风险 + `require_approval`、`pending_downgrade` 需确认、读取失败 fail-close。
- [ ] 1.5 `nexus_mcp.gateway`：`visible_definitions` → `ToolDefinition`（`source='mcp'`、`group='mcp'`、`deferrable=True`、外部前缀描述、schema 清洗）；注册名哈希防撞；执行器执行前复核目录 / 白名单 / 风险后再 `client.call`。
- [ ] 1.6 `nexus_core.native.tool_groups` 增加 `mcp` 组（默认关闭），接入 `preparation.py` / `tool_gates.py`。
- [ ] 1.7 管理 API：`/api/v1/tenants/{id}/mcp-services` 的 CRUD、`discover`、`enabled-tools`；`/agent-tools` 能力目录补 MCP 分组（只读 + 管理员开关）。

## 2. MCP 服务端
- [ ] 2.1 `mcp_run_tokens`：签发（单 Run、短时、可撤销）、哈希存储、解析与过期判定。
- [ ] 2.2 `nexus_mcp.server`（FastMCP）：`tools/list` 返回 Run 当前授权定义，`tools/call` 走 `AuthorizedToolGateway.execute` 完整管线。
- [ ] 2.3 API 挂载 `/mcp/runs/{token}`，Bearer 鉴权映射到 Run，提前于全局 Auth；稳定协议级错误不泄漏资源存在性。

## 3. 测试与文档
- [ ] 3.1 单元测试：连接参数校验与指纹失效、按工具启用、风险只升不降 + 降级确认、执行时复核、`McpError` / 输出 schema 分类、注册名哈希防撞。
- [ ] 3.2 集成测试：假 MCP 服务（stdio + HTTP）发现 / 调用 / 撤权后拒绝；服务端运行令牌生命周期（签发 / 调用 / 撤销 / 过期）。
- [ ] 3.3 文档：`docs/architecture.md` 2.7、`docs/roadmap.md` 第 7 步、`packages/mcp` 的 `README.md` / `docs/{requirements,design}.md`。
- [ ] 3.4 全量 `uv run --locked pytest` 与锁定前端类型检查 / 构建（若前端有改动）。
