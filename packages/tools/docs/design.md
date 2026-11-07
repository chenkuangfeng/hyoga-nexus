# 工具包设计

`nexus_tools` 负责工具注册、内置工具与授权网关。网关不授予权限：绑定、实时授权与审批是工具可用的唯一途径。工具调用加固见提案 `openspec/changes/archive/2026-11-06-tool-call-hardening`。

## 模块

| 模块 | 职责 |
| --- | --- |
| `registry` | `RegisteredTool`、`ToolRegistry`、调用适配 |
| `builtins` | 内置工具与编辑器目录（`catalog.py`，返回 `risk` 与派生的 `risk_level`） |
| `gateway` | `AuthorizedToolGateway`：执行管线、外置、截断、审批与放行接入 |
| `arguments` | 参数容错：`repair_json`、`coerce`、`describe_errors` |
| `output` | 头尾截断 `truncate` |
| `threats` | 工具输出注入特征扫描 |
| `policy` | 风险 × 访问级别 → `allow` / `ask` / `deny` |
| `guard` | 参数守卫：随包 JSON 规则、去混淆匹配 |

## 执行管线（`AuthorizedToolGateway.execute`）

1. 查找绑定与注册；实时授权（`ToolAccessPort.authorize`），之后按访问级别判断，`deny` 返回 `tool_authorization_denied`。
2. 参数预处理（`prepare_arguments`）：解析失败时尝试 `repair_json`；需要补齐未闭合字符串或括号即视为截断，返回 `tool_arguments_truncated`，不执行。再按 schema 保守转换类型（`coerce`），校验失败返回带字段路径与原因的 `tool_arguments_invalid`（最多 5 条、1000 字符，不回显参数值）。规范化后的参数写回 `ToolCall.arguments`。
3. 参数守卫（`guard.scan`）：`CRITICAL` 返回 `tool_guard_denied`，任何放行都不能绕过；`HIGH` 以 `reason='guard'` 进入审批，会话放行不适用；所有命中写事件 `tool.guard_finding`。
4. 审批：访问级别为 `ask`（含工具声明的 `requires_approval`）或守卫要求时进入。策略触发且非 `destructive` 的审批先查会话放行（`ToolAccessPort.grant`）。审批人修改的参数重新预处理。
5. 执行（超时、取消、副作用工具的 `interrupted` 语义不变）。
6. 输出：公开投影 → 注入扫描（命中时加告警标记并写事件 `tool.injection_suspected`，不拦截；`ask_user` 与 `read_tool_output` 不扫描）→ 外置（单条超过阈值，或本轮累计超过 `tool_turn_budget_chars`，且绑定了 `read_tool_output`）→ 头尾截断（70% 头、30% 尾，带原长度标记）。

`definitions()` 过滤掉访问级别为 `deny` 的工具，并按工具名排序，使绑定顺序不同的智能体版本得到字节相同的工具块。引擎每轮调用 `begin_turn()` 清零每轮输出计数。

## 风险与访问级别

`ToolDefinition.risk`：`read` / `probe` / `write` / `destructive`；省略时只读工具为 `read`，其余为 `write`；只读工具只能是 `read` 或 `probe`。`risk_level` 是派生属性（read/probe → low，write → medium，destructive → high），保留一个版本。

| access \ risk | read / probe | write | destructive |
| --- | --- | --- | --- |
| `read_only` | allow | deny | deny |
| `standard`（默认） | allow | allow | ask |
| `strict` | allow | ask | ask |

声明 `requires_approval` 的工具把 `allow` 提升为 `ask`。内置工具中 `run_skill_script` 为 `destructive`，`propose_memory_draft` 为 `write`，其余为 `read`。

## 参数守卫规则

规则文件在 `guard/rules/`，字段沿用 octop-harness 的 YAML（`id`、`tools`、`params`、`severity`、`patterns`、`exclude_patterns`、`description`、`remediation`），以 JSON 存放以免引入 YAML 依赖。`params` 为顶层参数名，`*` 表示任意深度的全部字符串值。匹配前生成去掉拆词引号与反斜杠的变体。规则加载失败抛 `GuardRuleError`，网关不能启动。

- `dangerous_shell_commands.json`：octop-harness 危险 shell 命令规则，作用于将来的 `shell` / `execute` / `bash` 工具。
- `skill_scripts.json`：作用于 `run_skill_script` 参数，`CRITICAL` 包括格式化磁盘、写裸设备、删除根目录、下载后管道执行、反向 shell。

## 端口

`ToolAccessPort` 必需 `authorize`、`start`、`finish`、`denied`；可选 `approval(call, reason, risk, rules)`、`grant(call)`、`observe(invocation_id, kind, payload)`、`spill`、`progress`。缺少可选方法时按「不支持」处理：不放行、不写事件，向严格一侧回退。

## 测试

`tests/test_tool_call_hardening.py`（参数容错、输出控制、循环检测、风险与访问级别、守卫）、`tests/test_tool_grants.py`（会话放行）、`tests/test_tool_output_spill.py`（外置）。

## 工具分组与调度

提案：`openspec/changes/2026-11-07-tool-expansion`。

- **分组**：`ToolDefinition.group` 在注册处声明（`builtins/registration.py`），分组本身（标签、默认开关、是否锁定）定义在 `nexus_core.native.tool_groups`。`base` 锁定，`sandbox`、`web`、`collab`、`schedule`、`media` 默认关闭。门控两层：可用性（`nexus_platform.runs.tool_gates`，部署侧事实）与智能体开关（`NativePolicy.tool_groups_enabled`）。两层都通过的组之外，工具既不出现在定义里，直接调用也返回 `tool_authorization_denied`（网关 `hidden_groups`）。门控只能收紧，授权、访问级别、守卫、审批照常。记忆、知识库、技能脚本三处仍在 `preparation.py` 按名过滤。
- **调度**：工具可声明 `concurrency(arguments)`，返回 `parallel` / `exclusive` / `serial(key)`。未声明时沿用「只读、幂等、无副作用、无审批才并行」。可能进入审批的调用（`gateway.may_suspend`：访问级别为 `ask`，或参数命中 `HIGH` 守卫规则）一律独占，因为挂起后从第一个待处理调用恢复，并行出去的兄弟调用会被重复执行。
- **沙箱工具**（`builtins/sandbox.py`，`sandbox` 组）：`sandbox_list_files`、`sandbox_read_file`、`sandbox_search_files`、`sandbox_write_file`、`sandbox_edit_file`、`sandbox_exec`。模型只看到 `/workspace` 与 `/outputs`。读写同一文件按路径串行，列目录和搜索独占。`sandbox_exec` 的风险：沙箱网络关闭时为 `write`，打开时为 `destructive`；`dangerous_shell_commands.json` 的规则同样作用于它。没有沙箱会话时返回 `sandbox_unavailable`，而不是抛出 Run 级错误。沙箱本身见 `packages/sandbox`。

## 渐进加载、schema 清洗与 Web 工具

- **渐进加载**（`bridge.py`）：`source == 'mcp'` 或声明 `deferrable` 的工具，其 schema 估算 token 之和达到 `NativePolicy.tool_search_min_tokens`（默认 6000，0 关闭）时，不再直接发给模型，改为 `tool_search` / `tool_describe` / `tool_call` 三个桥接工具。目录写在 `tool_search` 的描述里，Run 内工具块不变。`tool_call` 展开为真实工具后走完整网关管线；只能调用已绑定、已授权、未被分组隐藏、且确实被延迟的工具。当前没有内置工具声明 `deferrable`，所以现有行为不变，MCP 接入后生效。
- **schema 清洗**（`nexus_core.schema`）：发给供应商的是清洗后的副本（属性名、类型数组、缺失的 `properties` 与 `required`、`$ref` 旁的 `default`、顶层组合子），模型返回的参数由 `restore` 还原属性名。
- **Web 工具**（`builtins/web.py`、`web/`，`web` 组）：`web_search` 的后端注册表有 tavily、brave、searxng，请求形状按各家公开 API 编写，未对真实服务验证；`web_fetch` 逐跳校验（协议、端口 80/443/8080/8443、解析出的每个地址都必须是公网地址），连接到校验过的字面地址并保留 SNI，手动跟随最多 5 次重定向，正文有字节上限；结果带「外部网页内容」前缀，并经过网关的注入扫描。`[web].enabled` 默认关闭。
