# MCP：按工具启用的客户端 + 以运行令牌暴露授权工具的服务端

## 状态

已确认（2026-11-08）。全部决定已确认：1 传输（stdio + streamable HTTP + SSE）、2 运行令牌、3 默认禁用、4 OAuth 一起做、5 前后端一起做、6 官方 mcp SDK（锁 1.x）。

## 原因

路线图第 7 步「技能与 MCP」中技能部分（7.1）已基本完成，MCP 部分（7.2 客户端、7.3 服务端）仍是占位：`packages/mcp` 的三个子模块（`client`、`server`、`gateway`）都是 `"""Planned module; implementation pending."""`。前端工具箱页（提案 `2026-11-08-toolbox`）里 MCP 标签也标了「计划中，等对应后端」。本变更补齐 MCP 两端，使外部 MCP 服务能被安全接入并按工具启用，同时让平台把已授权工具以 MCP 协议暴露给 Codex / Claude Code 等外部 Runtime。

## 现状（读码所得）

| 部分 | 现状 |
| --- | --- |
| `packages/mcp` | `client` / `server` / `gateway` 三个占位 `__init__.py`，`pyproject.toml` 只依赖 `hyoga-nexus-core` |
| 工具网关 | `nexus_tools.gateway.AuthorizedToolGateway` 已具备完整管线：实时授权 → 参数预处理 → 守卫 → 审批 → 执行 → 注入扫描 → 外置 → 截断；`ToolDefinition.source` 已支持 `'mcp'` |
| 渐进加载 | `nexus_tools.bridge` 已实现 `tool_search` / `tool_describe` / `tool_call`，且 `source == 'mcp'` 的工具默认 `deferrable`，schema 超阈值即渐进加载 |
| schema 清洗 | `nexus_core.schema.sanitize` / `restore` 已实现供应商 schema 清洗与参数名还原 |
| 风险与审批 | `nexus_tools.policy.decide`（风险 × 访问级别）、`ToolDefinition.risk`（read/probe/write/destructive）、`action_approvals` / `action_grants` 已就绪 |
| 资源与绑定 | `platform_resources`、`agent_resource_bindings`（kind/资源 ID/版本）、`credential_references`（凭据引用）已就绪，技能就是按这套绑定的 |
| 运行令牌 | 未实现；`runs`、`action_approvals`、`ToolAccessPort.authorize` 已具备复核所需的事实源 |
| MCP SDK | 未引入官方 `mcp` Python SDK（`uv.lock` 无）；本变更采用官方 `mcp`（见决定 6） |

## 参考源码

本地副本 `/project/opensource/agents/`。下表为已读到的部分；`tasks.md` 第 0 节要求实施前补读其余。

| 项目 | 文件 | 采用什么 |
| --- | --- | --- |
| **WeKnora** | `agent/approval/mcp_risk.go` | MCP 工具风险只升不降：`显式设置 > 曾观察最高声明 > 当前声明`，服务端自行降级需工作区确认；`readOnlyHint` 才降为 `read`，否则 `write`；策略读取失败默认 fail-close |
| | `agent/tools/mcp_exposure.go` | 注册名 `mcp_{sanitize(服务)}_{sanitize(工具)}_{sha256(server_id \0 tool_name)[:8]}`；同名先注册者保留；执行前重新 `snapshot` + `checkEnabled` 复核目录与开关；渐进披露 |
| | `agent/tools/mcp_tool.go` | 描述带外部来源前缀；参数 schema 缺省为空对象；按服务配置超时；审批放行粒度 `mcp:{service_id}/{tool}#{schema_hash[:6]}` |
| | `agent/tools/{mcp_catalog,mcp_schema,mcp_call_guard}.go` | 工具目录状态机（loading/ready/error）、发现超时与重试、按工具启用、参数与输出校验分类 |
| | `router/routes_mcp_endpoint.go`、`middleware/mcp_endpoint_auth.go` | MCP 服务端挂载路径与 Bearer 鉴权、作用域化 principal（本仓库改为运行令牌） |
| **Octop** | `infra/connectors/custom_mcp.py` | 自定义 MCP 服务模型与连接参数（transport/url/headers/command/args/env） |
| | `infra/connectors/mcp_tool_cache.py` | 按用户缓存工具定义、连接参数指纹（transport/url/headers/command/args/env）失效 |
| | `infra/agents/middleware/mcp_output_schema.py` | MCP 工具输出 schema 校验失败分类 |
| **octop-harness** | `middleware/mcp_tools.py` | 按请求过滤 MCP 工具（opt-in 才暴露） |
| | `middleware/mcp_tool_error.py` | `McpError` 提示修正参数；输出 schema 失败提示「不要改参数重试」；异常组递归查找；控制流异常不软化 |
| | `mcp.py` | 参数 schema 清洗、空值剔除、LLM 工具名清洗、按服务前缀过滤 |
| **deer-flow** | `mcp/session_pool.py` | 持久会话池（按服务/作用域/事件循环/域键控，LRU 回收）；anyio 任务组所有权：会话 enter/exit 必须同一任务，用专用 owner task 关闭 |
| | `mcp/lifecycle.py` | 连接生命周期账本：每个服务一个不透明 epoch token，识别「删除后原样重加」；账本无效 fail-close |
| | `mcp/headers.py`、`mcp/context_headers.py`、`mcp/user_scoped_auth.py` | HTTP header 非法值前置校验（控制字符/非 ASCII/首尾空白）与大小写不敏感替换，防止凭据经异常信息泄漏 |
| | `mcp/tools.py` | 外部工具名在加载边界按 `^[A-Za-z0-9_-]+$` 规范化（延迟加载绕过 provider 校验的防御） |
| | `mcp/cache.py` | 工具缓存对账：秘密安全摘要（指纹）与完整快照分离，选择性淘汰 vs 全量重置 |
| | `mcp/interceptors.py` | 拦截器洋葱：凭据优先级「请求级 > 用户级 > 服务级」（本仓库简化为 `credential_references` 解析顺序） |
| | `mcp/oauth.py`、`mcp/oauth_store.py` | OAuth 授权码流与令牌存储（第一期仅借鉴形状，OAuth 列后续） |

## 范围

1. **MCP 客户端**（7.2）：连接外部 MCP 服务（stdio、streamable HTTP、SSE），发现工具，**按工具启用**（不默认开放整个服务），凭据引用与 OAuth，高风险工具审批，把启用的工具注册进 `AuthorizedToolGateway` 走完整管线。
2. **MCP 服务端**（7.3）：把某次 Run 已授权的工具以 MCP 协议暴露，使用**运行令牌**（短时、单 Run、可撤销），每次 `tools/list` 与 `tools/call` 都复核权限。
3. 前端：本期后端与前端一起做，工具箱 MCP 标签按 WeKnora 实现最小可用接入（见决定 5）。

不做：本地浏览器连接、MCP 服务端长期 endpoint token（WeKnora 模型）、外部 Runtime 适配器本身（第 4/5 步）。

## 待确认的决定

（无——全部决定已确认）

## 已确认的决定

1. **传输支持范围**（已确认，2026-11-08）：客户端支持 `stdio`（子进程）、`streamable HTTP` 与 `SSE`（兼容旧 MCP 服务）。stdio 按 hermes 的进程卫生标准（命令解析、环境收敛、子进程/孤儿回收）实现；SSE 按 WeKnora `boundedSSEConnection` 的「建连预算 vs 常驻流」分离 + hermes `sse_client` 的 `sse_read_timeout` 调参实现，SSRF 安全与同源重定向沿用 WeKnora。
2. **服务端鉴权模型**（已确认，2026-11-08）：只做运行令牌（短时、单 Run、可撤销，平台在 Run 启动时签发）；不做 WeKnora 的 endpoint 长期 token。
3. **按工具启用的默认值**（已确认，2026-11-08）：连接后发现的工具默认**全部禁用**，管理员逐个启用（`enabled_tools` 白名单）。
4. **OAuth**（已确认，2026-11-08）：本期实现 OAuth 授权码流（RFC 9728 动态客户端注册 + PKCE + 设备流按需），令牌按（租户、主体、服务）作用域存储与自动刷新；凭据优先级「请求级 > 用户级 > 服务级」；同时保留直接 header/env + `credential_references` 的静态凭据路径。
5. **前端范围**（已确认，2026-11-08）：后端与前端一起做，工具箱 MCP 标签按 WeKnora 实现最小可用接入（列表 / 启停 / 发现）。
6. **MCP SDK 选型**（已确认，2026-11-08）：使用官方 `mcp` Python SDK（`modelcontextprotocol/python-sdk`，锁 1.x；`mcp` 2.x 有破坏性变化，pin 住不自动升级）。不引入 `langchain-mcp-adapters`——它会拖进 LangChain 依赖；客户端自行把 `mcp.ClientSession` 适配到 `ToolDefinition` / `ToolRegistry`，服务端用 SDK 内置的 `mcp.server.fastmcp`。依据：Octop、deer-flow 同为 Python 栈且都用官方 SDK（分别锁 1.28.1 / 1.30.0），我们与其同源但不套 LangChain 适配层。

## 影响

- `packages/mcp`：实现 `client`（连接、发现、缓存、指纹、风险解析）、`server`（FastMCP 暴露授权工具 + 运行令牌）、`gateway`（把 MCP 工具桥接进 `AuthorizedToolGateway`）。
- `packages/platform`：新增 `nexus_platform/mcp/` 服务与持久化模型（`mcp_services`、`mcp_service_tools`、`mcp_tool_approvals`、`mcp_oauth_*`、`mcp_run_tokens`），迁移 `migrations/platform`。
- `nexus_core`：`native/tool_groups.py` 增加 `mcp` 组（默认关闭）。
- `apps/api`：MCP 服务管理路由与 MCP 服务端挂载（`/api/v1/tenants/{id}/mcp-services`、`/mcp/runs/{token}`）。
- 文档：`docs/architecture.md` 2.7、`docs/roadmap.md` 第 7 步、`packages/mcp` 模块文档。
- 依赖：新增官方 `mcp` Python SDK（锁 1.x，见决定 6），不引入 `langchain-mcp-adapters`。
