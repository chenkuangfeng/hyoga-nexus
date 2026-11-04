# Native 运行工作台：平台 Run 的 Web 界面

## 状态

已确认（UI 使用 TDesign，入口为独立导航项，v1 范围如提案所列，测试按提案执行）。实施状态见 tasks.md。

## 原因

后端已经具备完整的 Native Run 能力（会话、Run 提交、SSE 事件续读、取消、等待输入、审批、运行中追加指令、运行监督告警），但 Web 端没有任何界面使用它们。当前 `apps/web` 是 WeKnora 前端副本，对话页调用的是 WeKnora 接口（`/api/v1/sessions`、`/api/v1/agent-chat`），Nexus 后端并不提供这些接口。因此用户无法在界面里运行 Native 智能体，也无法看到运行监督的告警。

本提案新增一个只调用平台 API 的 Native 运行页，不改动现有 WeKnora 对话页。

## 范围

范围内（v1）：

- 入口与路由：新增页面 `/platform/native`（会话列表与新建）和 `/platform/native/sessions/:sessionId`（对话与运行）。
- 会话与智能体：列出当前空间的已发布智能体，选择后创建会话（`POST /tenants/{tenant_id}/sessions`）。
- 提交消息：`POST /tenants/{tenant_id}/sessions/{session_id}/runs`，每次提交携带 `Idempotency-Key`。队列返回 202 与 `queue_position` 时显示排队位置。
- 事件展示：订阅 `GET .../runs/{run_id}/events`（`Accept: text/event-stream`，断线用 `Last-Event-ID` 续读）。展示模型文本流、`tool.started` / `tool.completed` / `tool.failed`、终态与错误码。
- 运行监督告警条：`attention_required` 为 true 时显示告警，提供三个操作：
  - 继续等待：`POST .../runs/{run_id}/watchdog/acknowledge`。
  - 取消：`POST .../runs/{run_id}/cancel`。
  - 发送提示：`POST .../runs/{run_id}/steer`（运行中追加指令，携带幂等键，不新建 Run）。
- 等待输入：`wait_input` 时显示问题并提交回答（`POST .../runs/{run_id}/input`）。

范围外（明确不做，另行提案）：

- 审批（`approvals`）界面。v1 只在界面上显示"需要审批"的状态，不提供审批操作。
- 记忆草稿审核、模型分支（`model-branch`）、候选回答。
- 修改现有 WeKnora 对话页，或替换其接口。
- 移动端专门布局（保证窄屏可用，但不做专门优化）。

## 设计要点

- 状态以服务端为准：页面不保存权限或 Run 终态，每次进入页面都从 `GET .../runs/{run_id}` 读取。
- 事件按 `sequence` 去重并顺序渲染；断线后用 `Last-Event-ID` 续读，不重新提交 Run。
- 告警条与 `attention_required` 同步：确认后立即刷新 Run 视图，不等待下一次事件。
- 模型输出在 v1 中以纯文本显示（保留换行，不解析 Markdown），因此没有 HTML 注入路径。需要 Markdown 时另行使用现有安全渲染组件。
- 视觉与交互参照 `.codex/rules/frontend.md`，设计阶段使用 `ui-ux-pro-max` 技能。

## 已确认的决定

1. **UI 组件库**：TDesign。`.codex/rules/frontend.md` 记录的是 TDesign（2026-11-03 确认，与 WeKnora 一致），根目录 AGENTS.md 写的是 Element Plus，两者不一致，按 frontend.md 执行。
2. **入口位置**：独立导航项"Native 运行"（`stores/menu.ts`），路由为 `/platform/native`。
3. **v1 范围**：按上面的范围执行；审批与记忆草稿留到后续提案。
4. **测试方式**：组件与状态的单元测试；`pnpm build` 与浏览器用例需要在内存充足的环境执行。

## 影响

- 新增路由（`router/index.ts`）与导航项（`stores/menu.ts`）、页面与组件（`views/native/`）、组合式函数（`composables/useNativeRun.ts`）。
- 新增 `api/native-run-types.ts`（纯类型与校验）和 `api/native-runs.ts`（请求封装），不修改 WeKnora 对话相关代码。
- 文档：`apps/web/docs/design.md` 需要同步，删除其中已不存在的 `RuntimeControls.vue`、`api/native.ts` 描述，并补充新页面。
- 无后端改动，接口全部已存在。
