# 实施任务

状态：已确认（2026-11-06），决定 1–5 全部采用推荐方案。2026-11-06 用户指令开始实施，按节提交。

## 0. 准备

- [x] 0.1 阅读 WeKnora `registry.go`、`param_cast.go`、`param_validate.go`、`json_repair.go`、`truncate.go`、`policy/policy.go`、`approval/grants.go`。
- [x] 0.2 阅读 hermes `arg_coercion.py`、`agent/tool_guardrails.py`、`tool_result_storage.py`、`approval_floors.py`、`threat_patterns.py`。
- [x] 0.3 阅读 octop-harness `tool_guard`、`tool_order`，Octop `hitl_session.py`，deepseek `repeat-tool-reminder`。
- [x] 0.4 用户确认决定 1–5（全部采用推荐方案）。
- [x] 0.5 先更新文档：`docs/architecture.md` 2.5、2.7、2.9、2.11 标注计划与约束；`docs/roadmap.md` 新增 3.26，并在 7.2、8 写入决定 3 的约束。

## 1. 参数容错（`nexus_tools`）

- [x] 1.1 `arguments.repair_json`（含截断判定）与单元测试，覆盖 WeKnora 测试中的典型样例。
- [x] 1.2 `arguments.coerce` 与单元测试（标量、容器、单值包数组、`$ref`、不确定时保留原值）。
- [x] 1.3 `arguments.describe_errors` 与单元测试（路径排序、条数和长度上限、不回显参数值）。
- [x] 1.4 网关接入：参数预处理提前到审批之前，规范化参数写回 `ToolCall.arguments`；新增错误码 `tool_arguments_truncated`。
  - `nexus_tools.arguments`（`repair_json`、`coerce`、`describe_errors`）与 `gateway.prepare_arguments`；审批人修改的参数重新预处理。单引号只在文本不含双引号时整体替换。测试 `tests/test_tool_call_hardening.py`；`{bad` 这类未闭合参数改为 `tool_arguments_truncated`（同步更新引擎黄金用例与 Runtime 测试），全量 873 通过。

## 2. 输出控制

- [x] 2.1 `definitions()` 按名排序；测试：绑定顺序不同，输出字节相同。
- [x] 2.2 `output.truncate` 头尾截断，用于截断上限与外置预览。
- [x] 2.3 每轮总预算：`begin_turn()`、`tool_turn_budget_chars`，引擎每轮调用；测试超预算外置并能分页读回。
- [x] 2.4 `threats.scan` 与告警标记、`tool.injection_suspected` 事件；开关 `tool_injection_scan`。
  - `nexus_tools.output`、`nexus_tools.threats`（另加两条中文特征），网关 `begin_turn` 由 `ToolDispatcher` 每轮调用；worker 的 `ToolAccess.observe` 写 Run 事件。`NativePolicy` 一次加入 G18 的全部字段（含第 3、4 节用到的阈值与访问级别）并补齐设置页标签。预览长度不足 400 字符时只保留头部。全量 879 通过。

## 3. 循环检测（`nexus_runtimes`）

- [x] 3.1 `tool_guardrails` 纯状态机与单元测试（连续相同、周期 2–4、失败计数、写类工具成功清零、用户输入清零、阈值为 0 关闭）。
- [x] 3.2 接入 `ToolDispatcher`：提醒作为 continuation，停止抛 `tool_loop_detected`；状态随进度持久化，恢复后继续计数。
  - 提醒在相同签名第 `warn_at` 次及其后两次时各发一次（默认第 3、5 次），第 `stop_at` 次停止；同一工具连续失败第 `warn_at` 次提醒、第 `failure_stop_at` 次停止。用户追加指令（steer）或带用户答复恢复时清零。审批恢复路径（`recovery.resume_tools`）只执行挂起的调用，不计入检测。测试见 `tests/test_tool_call_hardening.py` 第 3 节（含 8 次相同调用以 `tool_loop_detected` 结束的端到端用例）。

## 4. 风险与访问级别

- [x] 4.1 `nexus_core.ToolDefinition.risk` 取代 `risk_level`，构造校验；更新内置工具取值。
- [x] 4.2 `nexus_tools.policy.decide` 与组合测试（3 种访问级别 × 4 种风险 × 是否声明 `requires_approval`）。
- [x] 4.3 网关 `definitions()` / `execute()` 接入；`NativePolicy.tool_access` 校验（非法值 422）。
- [x] 4.4 目录接口返回 `risk` 与推导出的 `risk_level`；更新接口测试。
  - `risk_level` 保留为由 `risk` 派生的只读属性（省略 `risk` 时只读工具为 `read`，其余为 `write`），`read_only` 工具只能是 `read`/`probe`。网关参数 `tool_access` 由 worker 按 `NativePolicy.tool_access` 传入；非法值在设置与草稿校验中被拒绝（422）。全量 914 通过。

## 5. 会话放行

- [x] 5.1 迁移：`action_grants` 表（架构 2.11 的 ActionGrant）、`action_approvals.reason` 列；测试升级和降级。
- [x] 5.2 `resolve` 支持 `remember`；`destructive` 或守卫触发的审批拒绝 `session`（422）。
- [x] 5.3 `DurableRuntimeStore.approval(call, reason)` 与 `grant` 查询；`approval.grant_used` 审计。
- [x] 5.4 `GET/DELETE sessions/{session_id}/tool-grants` 接口（404、审计）。
- [x] 5.5 pytest：放行生效、版本变化失效、撤销后立即生效、非所有者 404、`destructive` 不可放行。
  - `action_approvals` 另记 `risk`（判断能否放行）；待审列表与 `approval.requested` 事件带 `reason`、`rememberable` 供界面决定是否显示按钮。网关对 `destructive` 工具不查放行；端口的 `approval` 不接受 `reason` 时按旧签名调用。会话删除时清理放行未做：平台目前没有删除会话的入口。测试 `tests/test_tool_grants.py`，全量 918 通过。

## 6. 参数守卫

- [x] 6.1 `nexus_tools.guard` 规则加载、预编译、规范化匹配；规则文件格式错误时启动失败。
- [x] 6.2 随包规则 `dangerous_shell_commands.yaml`、`skill_scripts.yaml` 与样例测试（含混淆写法）。
- [x] 6.3 网关接入：`CRITICAL` 拒绝、`HIGH` 以 `reason='guard'` 审批（忽略会话放行）、`MEDIUM` 只记事件；`tool.guard_finding` 事件。
  - 调整：规则文件改用 JSON（字段与 octop-harness YAML 相同），因为 `nexus_tools` 不依赖 PyYAML，不为此新增依赖；`dangerous_shell_commands.json` 由 octop-harness 的 YAML 转换（20 条，作用于 `shell`/`execute`/`bash`），`skill_scripts.json` 6 条。守卫审批的 `approval.requested` 事件带 `guard_rules` 供审批卡显示。全量 926 通过。

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
