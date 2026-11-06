# 规格：工具调用加固

来源：`openspec/changes/2026-11-06-tool-call-hardening`（草案，待确认）。

## 需求

### R1 参数容错
- 网关在校验前修复非截断类 JSON 畸形；判断为截断时不执行，返回 `tool_arguments_truncated`。
- 网关按 schema 做保守的类型转换，无法确定时保留原值。
- 校验失败返回 `tool_arguments_invalid`，文本包含字段路径和原因，最多 5 条、不超过 1000 字符，不回显参数值。
- 审批、守卫、调用记录和实际执行使用同一份规范化后的参数。

### R2 输出控制
- 工具定义按名称排序输出。
- 超过上限的输出保留头部 70% 和尾部 30%，并标注原长度；外置预览同样使用头尾预览。
- 绑定 `read_tool_output` 时，同一轮工具输出累计超过 `tool_turn_budget_chars` 后，后续结果外置。
- `tool_injection_scan` 开启时，命中注入特征的输出前加告警标记，并产生 `tool.injection_suspected` 事件；输出本身不拦截、不改写。

### R3 循环检测
- 同一 Run 内（工具、规范化参数、结果摘要）连续相同，或出现周期为 2–4 的循环时计数；达到 `tool_repeat_warn_at` 时提醒模型，达到 `tool_repeat_stop_at` 时 Run 以 `tool_loop_detected` 失败。
- 同一工具连续失败达到 `tool_failure_stop_at` 时 Run 以 `tool_loop_detected` 失败；其他有副作用的工具成功执行一次即清零。
- 用户新输入清空计数；阈值为 0 表示关闭对应检测；计数随 Run 进度持久化。

### R4 风险与访问级别
- 每个工具定义声明 `risk`：`read`、`probe`、`write` 或 `destructive`；只读工具只能是 `read` 或 `probe`。
- `tool_access` 取值 `read_only`、`standard`（默认）、`strict`，与风险的组合按设计第 5 节的表格决定允许、询问或拒绝；`requires_approval` 把允许提升为询问。
- 拒绝的工具不出现在工具定义中，直接调用返回 `tool_authorization_denied`。

### R5 会话放行
- 审批决定可选 `remember='session'`，之后同一会话、同一智能体版本中同名工具因访问级别或 `requires_approval` 产生的审批自动通过。
- `destructive` 工具和守卫触发的审批不能会话放行，请求返回 422。
- 放行可通过 `GET/DELETE /api/v1/tenants/{tenant_id}/sessions/{session_id}/tool-grants` 查看和撤销；只有会话所有者可以访问，其他人返回 404；授予、使用、撤销都写审计；撤销后下一次调用即重新审批。

### R6 参数守卫
- 网关在授权之后、审批之前扫描参数字符串值，匹配前做去混淆规范化。
- `CRITICAL` 命中返回 `tool_guard_denied`，任何放行都不能绕过；`HIGH` 命中进入审批，会话放行不能跳过；`MEDIUM` 只记录。
- 所有命中都产生 `tool.guard_finding` 事件（规则 ID、严重级别、工具名），返回给模型的文本不含参数原文。
- 规则文件格式错误时网关不能启动。
