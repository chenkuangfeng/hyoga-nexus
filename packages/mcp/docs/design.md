# MCP 包设计

`nexus_mcp` 只做协议与投影：不持有数据库、不读部署配置、不授予权限。平台（`nexus_platform.mcp`）负责持久化、授权、令牌与审计；应用入口（`apps/worker`、`apps/api`）负责装配。

## 模块

| 模块 | 职责 |
| --- | --- |
| `_sdk.py` | 唯一允许 `import mcp.*` 的适配层。SDK 2.x 的 `ClientSession`、`stdio_client`、`streamable_http_client`、`sse_client`、`MCPServer` 等名称在此探测并对旧别名回退；`sdk_httpx()` 统一 SDK 使用的 httpx 版本，避免与包内直接请求混用 |
| `client/config.py` | 连接参数归一与校验：`TRANSPORTS`、`AUTH_TYPES`、header 非法值、大小写不敏感合并；`fingerprint`（秘密值不进入摘要）；`new_epoch` |
| `client/discovery.py` | `discover` / `call` / `validate_output`；stdio 会话池 `StdioSessionPool` |
| `client/errors.py` | `McpError` 及稳定子类；`is_unauthorized` 沿 `__cause__` / `__context__` 识别 401 |
| `client/names.py` | 外部工具名清洗、注册名、`tool_ref`、外部来源描述 |
| `oauth.py` | OAuth 2.1 协议：`AuthorizationServer` / `OAuthClient` / `TokenSet`、发现、动态注册、PKCE URL、换码、刷新 |
| `gateway/` | `tool_definition`（`source='mcp'`、`group='mcp'`、`deferrable=True`）、`make_registered_tool`、执行器协议 |
| `server/` | `RunMCPServer`（`tools/list`）与 `streamable_http_app` |

## 连接与发现

1. `validate_config` 归一配置并拒绝非法参数；`assert_resolved` 拒绝未解析的凭据引用。
2. `discover` 对 HTTP 传输在握手失败时重连一次；stdio 不重试。任何 401 / 授权挑战立即抛 `McpUnauthorized`，不再用同一令牌重试。
3. 发现结果由平台按指纹写入工具缓存；平台把「服务、工具、风险」投影为 `ToolDefinition`，注册名哈希避免不同服务同名工具相撞。
4. `call` 只拿已解析的连接配置执行，不理解授权；语义错误（服务端拒绝、输出 schema 不符）转成稳定错误码。

stdio 会话池按（服务、作用域、事件循环）键控，enter/exit 必须由同一任务完成，LRU 回收；发现用的一次性连接用完即断开。HTTP 传输每次调用新建会话，401 时平台可安全地换令牌重试。

## 指纹与 epoch

`fingerprint` 只覆盖决定「有哪些工具」的参数：传输、url、command、args、headers/env 的键与凭据引用 ID、OAuth 的 `auth_type` / scopes / client_id / 元数据地址 / client_secret 引用 ID。秘密值、令牌与 `client_secret` 明文不进入摘要，轮换秘密不会误清工具缓存。`config_epoch` 是独立的生命周期账本：删除后原样重建的服务也得到新 epoch，旧 stdio 会话不会被复用。

## OAuth

协议层与平台层分开：

- `nexus_mcp.oauth` 只做 HTTP 请求，可注入 `httpx.AsyncClient`，便于用 `MockTransport` 测试。发现顺序为 RFC 9728 受保护资源元数据 → RFC 8414 授权服务器元数据 → OIDC 发现；issuer 必须与文档来源同源；除回环开发地址外必须 HTTPS。动态注册按 RFC 7591 提交 `redirect_uris`、`grant_types`、`token_endpoint_auth_method`。
- `nexus_platform.mcp.oauth` 决定状态。`state` 是部署 Fernet 密钥加密的 JSON（主体、服务、PKCE verifier、回调地址、前端路径、10 分钟过期），因此不需要额外的 state 表，PKCE verifier 也不会到浏览器。回调是公开接口，只能通过解密 state 获知主体。
- 令牌按 `(tenant_id, principal_id, service_id)` 加密保存；动态注册的客户端按 `(tenant_id, service_id)` 保存，`client_secret` 同样加密。绑定字符串参与密文认证，行与行之间不能互换密文。
- 使用前 30 秒余量判断是否刷新；刷新在支持行锁的数据库上 `SELECT ... FOR UPDATE` 并 `populate_existing` 重读，避免多进程同时消费同一个 refresh token。
- 刷新成功立即提交：旋转后的 refresh token 可能已使旧值失效，调用方后续失败不应把轮换回滚。失效授权（`invalid_grant` / 过期）删除令牌并提交，再抛 `mcp_oauth_required`；`invalid_client` / `unauthorized_client` 同时删除动态注册。
- 资源服务器 401：客户端抛 `McpUnauthorized`，平台强制刷新一次并重试一次；第二次失败按普通错误返回，不再循环。

## 服务端

`RunMCPServer` 以 SDK 的 `MCPServer` 为基类，`tools/list` 由注入的 `definitions()` 提供（平台已过滤 `deny` 与未授权项）。`streamable_http_app` 默认无状态，供 API 以 `/mcp/runs/{token}` 挂载；`tools/call` 的完整网关执行依赖外部 Runtime 适配器（路线图第 4/5 步），当前只保留协议骨架与稳定的鉴权错误。

## 错误码

| 场景 | 码 |
| --- | --- |
| 连接失败 / 调用超时 | `mcp_connection_failed` / `mcp_call_timeout` |
| 发现超时 | `mcp_discovery_timeout` |
| 服务端拒绝、输出不符 | `mcp_call_rejected` / `mcp_output_schema_failed` |
| 服务停用、工具不可用 | `mcp_service_disabled` / `mcp_unavailable` |
| 401 且需刷新 | `mcp_unauthorized`（内部，不直接到达模型） |
| OAuth 未授权 / 刷新被拒 | `mcp_oauth_required` |
| OAuth 配置或元数据无效 | `mcp_oauth_configuration_invalid` |
| OAuth 端点瞬时失败 | `mcp_oauth_unavailable` |
