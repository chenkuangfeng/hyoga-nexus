# hyoga-nexus-mcp

MCP 客户端、服务端与工具桥。客户端连接外部 MCP 服务（stdio、streamable HTTP、SSE），发现工具、按工具启用并把它们接入 `AuthorizedToolGateway`；服务端把某次 Run 已授权的工具以 MCP 协议暴露给外部 Runtime。所有 MCP 工具调用都走与内置工具相同的授权、审批、守卫、注入扫描与外置管线。

## 模块结构

| 路径 | 职责 |
| --- | --- |
| `_sdk.py` | 唯一允许 `import mcp.*` 的适配层：SDK 2.x 名称探测与别名回退，`httpx` / `httpx2` 边界 |
| `client/config.py` | 连接参数校验（transport、url、headers/env、OAuth 配置）、header 非法值检查、`fingerprint`、`config_epoch` |
| `client/discovery.py` | `discover` / `call`：超时、HTTP 重连一次、stdio 会话池、输出 schema 校验、`McpError` 分类与 401 识别 |
| `client/errors.py` | 稳定错误码；`McpUnauthorized` 与 `is_unauthorized`（沿异常链识别 401） |
| `client/names.py` | 外部工具名清洗、注册名哈希、外部来源描述前缀 |
| `oauth.py` | OAuth 2.1 协议层：RFC 9728 / RFC 8414 / OIDC 发现、RFC 7591 动态注册、PKCE 授权 URL、换码与刷新 |
| `gateway/` | `ToolDefinition` 投影、注册工具与执行器协议（执行器由应用装配） |
| `server/` | `RunMCPServer`（`tools/list`）与 streamable HTTP 应用工厂；`tools/call` 的完整管线执行待接入外部 Runtime 通道 |

平台侧的持久化、授权、令牌与审计在 `nexus_platform.mcp`；worker 装配在 `apps/worker/src/nexus_worker/mcp_tools.py`。

## 当前能力

- 传输：stdio（子进程 + 进程卫生）、streamable HTTP、SSE（事件间隔与建连预算分离、TLS / 响应体上限 / 同源重定向收紧）。
- 发现与启用：发现的工具默认全部禁用，管理员按工具开启；连接参数指纹与 `config_epoch` 决定缓存失效与会话重建。
- 风险：`readOnlyHint` 为真才视为 `read`，否则 `write`；显式风险 > 曾观察最高声明 > 当前声明，服务端自行降级须工作区确认。
- OAuth（`auth_type='oauth'`，仅 HTTP 传输）：授权码 + PKCE（S256）；未预置客户端时动态注册并按（租户、服务）复用；令牌按（租户、主体、服务）加密存储；30 秒余量惰性刷新；401 恰好一次 refresh + 一次重试；授权被拒删除令牌并返回 `mcp_oauth_required`。动态令牌优先于服务级静态 `Authorization` header，`headers` / `env` 的 `credential_references` 路径保留。
- 服务端：`tools/list` 返回 Run 当前授权定义；运行令牌短时、单 Run、可撤销，每次调用复核权限。

## 使用

包本身不建数据库、不读部署配置：调用方把已解析的连接配置（含 `Authorization` header）交给 `discover` / `call`，把已确认的服务、工具与风险交给 `gateway`；令牌生命周期由 `nexus_platform.mcp.oauth` 负责。

```python
from nexus_mcp import client

specs = await client.discover(resolved_config, timeout=30)
result = await client.call(resolved_config, "get_repo", {"repo": "hyoga"}, timeout=30)
```

## 限制

- `tools/call` 经 `AuthorizedToolGateway` 的完整执行依赖外部 Runtime 适配器（路线图第 4/5 步）；当前服务端只完整实现 `tools/list`。
- 设备流（device flow）未实现；OAuth 仅支持授权码 + PKCE。
- 外部工具名、描述与 schema 均视为不可信输入，进入模型前会清洗并加来源前缀。

## 文档

- 需求：`docs/requirements.md`
- 设计：`docs/design.md`
- 提案与任务：`openspec/changes/2026-11-08-mcp/`
