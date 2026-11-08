# 技术设计：MCP

## 1. 总体结构

沿用「平台管数据与授权，`packages/mcp` 管协议，`nexus_tools` 管执行管线」的分层：

```text
外部 MCP 服务 ◀── mcp.client（stdio / streamable_http）──┐
                                                        │ 发现 / 缓存 / 指纹
      admin API ──▶ nexus_platform.mcp.service ── 持久化 ┘
                                                        │ 启用白名单 + 风险策略
                                                        ▼
      Run 准备 ──▶ 把已绑定、已启用的 MCP 工具注册进 AuthorizedToolGateway（source='mcp'）
                                                        │
      Codex / Claude ◀── mcp.server（FastMCP，运行令牌）──▶ 同一套 ToolGatewayPort
```

- `nexus_platform/mcp/`：领域服务（服务 CRUD、工具目录、启用白名单、风险策略、运行令牌）与持久化模型。
- `nexus_mcp/client.py`：连接外部服务、发现工具、按用户缓存（租户/服务粒度）、连接指纹。
- `nexus_mcp/server.py`：FastMCP 服务端，把 Run 的授权工具暴露出来。
- `nexus_mcp/gateway.py`：把缓存/策略解析出的工具定义与执行器接进 `AuthorizedToolGateway` 的注册表（桥接，不自行授权）。

## 2. 数据模型（`migrations/platform`）

### `mcp_services`
- `id` UUID 主键；`tenant_id` FK tenants；`name` 租户内唯一；`description`；`transport`（`stdio` / `streamable_http`）；`config` JSON（连接参数，秘密为引用）；`enabled` bool；`created_by`；`created_at` / `updated_at`。

### `mcp_service_tools`
- 每（服务、工具名）一行：`service_id`、`tool_name`、`enabled` bool（白名单）、`input_schema` JSON（缓存）、`description`、`read_only_hint` bool、`catalog_status`（`loading` / `ready` / `error`）、`catalog_error`、`fingerprint`（连接参数指纹）、`config_epoch`（配置代际，见生命周期账本）、`updated_at`。
- 工具定义缓存与启用白名单合在一张表，避免另设缓存表。

### `mcp_tool_approvals`
- 每（tenant、service、tool）一行：`explicit_risk`（可空，`read`/`write`/`destructive`，MCP 工具一般无 `probe`）、`observed_risk`（曾观察到的最高声明）、`require_approval` bool、`pending_downgrade` bool、`updated_at`。
- 生效风险在服务层计算，不落库派生值。

### `mcp_run_tokens`
- `token_hash`（SHA-256 前缀）主键；`run_id` FK runs；`tenant_id`；`expires_at`；`revoked_at`；`created_at`。
- 明文令牌只在签发响应中出现一次；其余位置只存哈希。

迁移放 `migrations/platform`，按既有 Alembic 约定；空库升级、已有库升级、重复执行均需验证。

## 3. 模块与接口

### `nexus_mcp.client`
- `fingerprint(config: dict) -> str`：与 Octop 一致，仅取 `transport/url/headers/command/args/env`，`headers`/`env` 取「键 + 引用 ID」排序后哈希。
- `discover(config, timeout=30) -> list[MCPToolSpec]`：建立会话、`list_tools`、读取 server instructions；HTTP 失败断开重连一次，stdio 不重试。
- `call(config, tool_name, arguments, timeout) -> ToolResult`：调用并捕获 `McpError` 与输出 schema 错误分类。
- 会话池按（服务、作用域、事件循环、域）键控复用，LRU 回收；遵守 anyio 任务组所有权：会话的 enter/exit 必须同一任务，用专用 owner task 关闭（deer-flow `session_pool.py`）。
- 连接生命周期账本：每服务一个不透明 epoch token，配置「删除后原样重加」也能感知变化并重建绑定；账本无效 fail-close（deer-flow `lifecycle.py`）。
- 写入 HTTP header 前校验非法值（控制字符、非 ASCII、首尾空白），并按大小写不敏感替换既有同名 header，防止凭据经异常信息泄漏（deer-flow `headers.py`）。

### `nexus_platform.mcp.service`
- `create/update/delete/list/get`（权限 `tools:manage`，读为活跃成员）。
- `discover_tools` / `set_enabled_tools`：发现后以指纹写入缓存，白名单只接受已发现工具名。
- `policy(tool) -> (risk, require_approval)`：实现风险只升不降（WeKnora `mcp_risk.go` 语义）；`observe_declared_risk` 在发现时写入 `observed_risk`。
- `issue_run_token(run) -> token`、`resolve_run_token(token) -> Run`、`revoke_run_token(run)`。
- `visible_definitions(run) -> list[ToolDefinition]`：绑定的服务 ∩ 启用白名单 ∩ 风险策略 → `ToolDefinition`。

### `nexus_mcp.gateway`
- `register_mcp_tools(registry, run, services)`：把 `visible_definitions` 注册为 `RegisteredTool`，`source='mcp'`、`group='mcp'`、`deferrable=True`；执行器在执行前重新走 `nexus_platform.mcp.service.policy` 与 `check_enabled`，再调 `client.call`。
- 注册名哈希防撞与先注册者保留沿用 `ToolRegistry` 的重复名拒绝。
- 外部工具名在加载边界按 `^[A-Za-z0-9_-]+$` 规范化后再进注册名与 `tool_search` 目录，防延迟加载绕过 provider 校验（deer-flow `tools.py`）。

### `nexus_mcp.server`
- FastMCP 实例，`tools/list` 从 `visible_definitions` 取；`tools/call` 调用 `AuthorizedToolGateway.execute`（复用完整管线，含审批、守卫、审计）。
- 挂载在 API 进程 `/mcp/runs/{token}`（或可配置前缀），Bearer 鉴权映射到 Run；不在全局 Auth 中间件之后，参照 WeKnora `routes_mcp_endpoint.go` 的提前挂载。

## 4. 关键流程

### 发现与启用
1. 管理员创建服务（配置含凭据引用）→ 存 `mcp_services`。
2. 管理员触发「发现工具」→ `client.discover` → 以指纹写 `mcp_service_tools`（默认 `enabled=false`，状态 `ready`）。
3. 管理员提交 `enabled_tools` 白名单 → 校验后更新 `enabled=true`。
4. 后续 Run 准备时 `visible_definitions` 只取白名单内、服务启用的工具。

### 执行时复核（复用网关）
- 注册的执行器在每次调用前：重读服务（存在、启用）→ 重读白名单（工具仍在）→ 重读风险策略（可升不可降）→ 通过后 `client.call`。
- 任一步失败返回 `mcp_unavailable`，不直接调用外部服务。

### 服务端调用
- Codex/Claude 适配器（第 4/5 步）在 Run 启动时向平台请求运行令牌，令牌绑定 Run 与主体/空间。
- 外部 Runtime 带令牌访问 `/mcp/runs/{token}`：`tools/list` 返回 `visible_definitions`；`tools/call` 经 `AuthorizedToolGateway.execute` 复核授权并审计。

## 5. 错误处理
- 连接失败：`mcp_connection_failed`；发现超时：`mcp_discovery_timeout`；服务停用：`mcp_service_disabled`；工具未启用 / 已移除：`mcp_unavailable`。
- `McpError` → 参数修正提示；输出 schema 失败 → 「不要改参数重试」（octop-harness `mcp_tool_error.py`）。
- 策略读取失败 fail-close（临时 `write` + 审批），不静默放行。
- 运行令牌：过期/撤销/不存在 → 协议级 `unauthorized`，不泄漏资源存在性。

## 6. 边界情况
- 同名工具（服务改名、哈希前缀碰撞）：注册名哈希防撞 + 先注册者保留。
- 服务配置变更但工具缓存未刷新：执行前复核白名单与风险，发现工具列表以指纹失效重发现。
- stdio 会话泄漏：会话池回收 + 发现后断开（list_tools 一次性连接）；配置变化经 epoch 账本重建绑定，避免旧会话带旧配置继续用。
- 撤权后下一次调用拒绝：`visible_definitions` 与执行器都实时查库。
