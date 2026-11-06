# 实施任务

状态：草案，待确认（2026-11-06）。确认前不编码。

## 0. 准备

- [x] 0.1 阅读 WeKnora `registry.go`、`param_cast.go`、`param_validate.go`、`json_repair.go`、`truncate.go`、`policy/policy.go`、`approval/grants.go`。
- [x] 0.2 阅读 hermes `arg_coercion.py`、`agent/tool_guardrails.py`、`tool_result_storage.py`、`approval_floors.py`、`threat_patterns.py`。
- [x] 0.3 阅读 octop-harness `tool_guard`、`tool_order`，Octop `hitl_session.py`，deepseek `repeat-tool-reminder`。
- [ ] 0.4 用户确认决定 1–5。

## 1. 参数容错（`nexus_tools`）

- [ ] 1.1 `arguments.repair_json`（含截断判定）与单元测试，覆盖 WeKnora 测试中的典型样例。
- [ ] 1.2 `arguments.coerce` 与单元测试（标量、容器、单值包数组、`$ref`、不确定时保留原值）。
- [ ] 1.3 `arguments.describe_errors` 与单元测试（路径排序、条数和长度上限、不回显参数值）。
- [ ] 1.4 网关接入：参数预处理提前到审批之前，规范化参数写回 `ToolCall.arguments`；新增错误码 `tool_arguments_truncated`。

## 2. 输出控制

- [ ] 2.1 `definitions()` 按名排序；测试：绑定顺序不同，输出字节相同。
- [ ] 2.2 `output.truncate` 头尾截断，用于截断上限与外置预览。
- [ ] 2.3 每轮总预算：`begin_turn()`、`tool_turn_budget_chars`，引擎每轮调用；测试超预算外置并能分页读回。
- [ ] 2.4 `threats.scan` 与告警标记、`tool.injection_suspected` 事件；开关 `tool_injection_scan`。

## 3. 循环检测（`nexus_runtimes`）

- [ ] 3.1 `tool_guardrails` 纯状态机与单元测试（连续相同、周期 2–4、失败计数、写类工具成功清零、用户输入清零、阈值为 0 关闭）。
- [ ] 3.2 接入 `ToolDispatcher`：提醒作为 continuation，停止抛 `tool_loop_detected`；状态随进度持久化，恢复后继续计数。

## 4. 风险与访问级别

- [ ] 4.1 `nexus_core.ToolDefinition.risk` 取代 `risk_level`，构造校验；更新内置工具取值。
- [ ] 4.2 `nexus_tools.policy.decide` 与组合测试（3 种访问级别 × 4 种风险 × 是否声明 `requires_approval`）。
- [ ] 4.3 网关 `definitions()` / `execute()` 接入；`NativePolicy.tool_access` 校验（非法值 422）。
- [ ] 4.4 目录接口返回 `risk` 与推导出的 `risk_level`；更新接口测试。

## 5. 会话放行

- [ ] 5.1 迁移：`tool_approval_grants` 表、`action_approvals.reason` 列；测试升级和降级。
- [ ] 5.2 `resolve` 支持 `remember`；`destructive` 或守卫触发的审批拒绝 `session`（422）。
- [ ] 5.3 `DurableRuntimeStore.approval(call, reason)` 与 `grant` 查询；`approval.grant_used` 审计。
- [ ] 5.4 `GET/DELETE sessions/{session_id}/tool-grants` 接口（404、审计）。
- [ ] 5.5 pytest：放行生效、版本变化失效、撤销后立即生效、非所有者 404、`destructive` 不可放行。

## 6. 参数守卫

- [ ] 6.1 `nexus_tools.guard` 规则加载、预编译、规范化匹配；规则文件格式错误时启动失败。
- [ ] 6.2 随包规则 `dangerous_shell_commands.yaml`、`skill_scripts.yaml` 与样例测试（含混淆写法）。
- [ ] 6.3 网关接入：`CRITICAL` 拒绝、`HIGH` 以 `reason='guard'` 审批（忽略会话放行）、`MEDIUM` 只记事件；`tool.guard_finding` 事件。

## 7. 前端

- [ ] 7.1 `api/native-runs.ts`：`resolveApproval` 支持 `remember`；新增放行列表与撤销接口及映射测试。
- [ ] 7.2 审批卡「本会话允许」按钮（`destructive` 和守卫触发时隐藏），守卫审批显示命中的规则。
- [ ] 7.3 对话页「已放行的工具」列表与撤销。
- [ ] 7.4 智能体编辑器工具分区：访问级别选项；工具列表显示 `risk`。
- [ ] 7.5 文案：所有语言包补齐新增键。

## 8. 文档与规格

- [ ] 8.1 新建 `packages/tools/docs/design.md`（执行管线、容错、输出、风险、守卫）；更新 `packages/runtimes/docs/design.md`（循环检测）、`packages/platform/docs/design.md`（会话放行）。
- [ ] 8.2 `docs/architecture.md` 工具网关一节；路线图第 7.2、8 步写入决定 3 的约束。
- [ ] 8.3 新增规格 `openspec/specs/tool-call-hardening/spec.md`（由本变更的 `specs/` 归档生成）。
