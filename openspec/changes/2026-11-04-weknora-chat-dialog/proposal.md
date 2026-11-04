# 严格参考 WeKnora 实现聊天对话框

## 状态

待确认（尚未编码）。确认范围与下列「待确认的决定」后再进入实施。

## 原因

- 主聊天路由（`/platform/chat/:chatid`、`/platform/creatChat`、`/platform/knowledge-bases/:kbId/creatChat`）仍是「规划中」占位页（`views/placeholder/PlannedPage.vue`）。用户在主导航中无法进行对话。
- `apps/web/src/views/chat/` 已是 WeKnora 前端副本（`index.vue` 与 `components/` 与参考版本仅相差 Fork 键名、工具卡片等少量差异），但它只被助手面板引用，且调用的是 WeKnora 接口（`/api/v1/sessions`、`/api/v1/agent-chat`、`api/chat/*` 等），Nexus 后端不提供这些接口。
- 已实现的 `/platform/native` 是纯文本运行页（见 `2026-11-04-native-run-workbench`），与 WeKnora 的对话交互不一致。用户决定：主聊天路由改为 WeKnora 风格的对话页，接入 Nexus 的会话与 Run API。

参考源码：WeKnora `frontend/`，固定版本 `e1f9a6166`（本地副本 `/project/opensource/knowledge-base/WeKnora`，远端 https://github.com/Tencent/WeKnora/tree/e1f9a6166/frontend）。

## 范围

范围内（v1）：

1. 路由与入口
   - `/platform/creatChat`：新建对话页（WeKnora 的欢迎页与输入区布局），选择已发布智能体后创建会话。
   - `/platform/chat/:chatid`：会话页，展示历史消息与新消息。
   - `/platform/knowledge-bases/:kbId/creatChat`：见下方「待确认的决定」第 3 项。
   - 侧栏会话列表沿用 WeKnora 的分组与操作（重命名、删除、置顶等），数据来自 `GET /tenants/{tenant_id}/sessions`。
2. 对话界面（严格对齐 WeKnora）
   - 消息区：用户消息与助手消息气泡、Markdown 渲染（复用 `chatMarkdownRenderer.ts` 与安全净化），代码块、表格、数学公式的渲染行为与参考一致。
   - 输入区（`Input-field.vue`）：多行输入、发送与停止、排队提示、忙时 steer（追加指令）。
   - 运行过程：助手运行时的过程时间线（`AgentStreamDisplay.vue`）、工具调用卡片（`ToolResultRenderer.vue`）、审批与等待输入卡片（`ToolApprovalCard.vue`、`AskUserCard.vue`）。
   - 运行监督告警条沿用 `NativeWatchdogBanner` 的语义（继续等待、取消、发送提示）。
3. 数据接入（只调用 Nexus 已有接口）
   - 提交：`POST .../sessions/{session_id}/runs`（携带 `Idempotency-Key`）。
   - 事件：`GET .../runs/{run_id}/events`（SSE + `Last-Event-ID`），复用 `api/native-runs.ts` 与 `nativeRunState.ts` 的按 `sequence` 去重逻辑。
   - 历史消息：`GET .../sessions/{session_id}/messages`。
   - 取消、等待输入回答、告警确认、追加指令：沿用已有的 native API 封装。
4. 功能裁剪（Nexus 后端尚无对应能力，v1 不做，界面上明确隐藏或禁用，而不是保留 WeKnora 接口调用）
   - 知识库检索、文档引用与引用弹窗（`ChatReferencesDrawer`、`ChatCitationFloat`）。
   - 临时附件上传（`api/chat/temporary-attachments`）。
   - 推荐追问（`api/message-suggestion`）、后台任务（`api/chat/background-work`）。
   - 嵌入式渠道（`api/embed`）与自动化会话（`automationConversation`）。
   - 由 WeKnora 知识库、Wiki、模型列表等接口支撑的入口。
5. 清理
   - 助手面板（`AssistantPanel.vue`）改为使用同一套对话组件，不再调用 WeKnora `api/chat`。
   - `/platform/native` 与 `NativeSessionView` 合并进新会话页，旧路径重定向到新会话页。

范围外（明确不做）：

- 后端改动：所有接口已存在；缺失的 RAG 与附件能力另行提案。
- 审批的完整操作（沿用 native-run-workbench 的 v1 约束，仅展示状态，审批按钮另行提案，除非待确认决定第 2 项另有选择）。
- 移动端专门布局（保证窄屏可用，不做专门优化）。

## 待确认的决定

1. **功能裁剪的范围**：第 4 项中的功能在 v1 直接隐藏，还是保留入口并显示「暂未开放」？推荐：隐藏，避免出现不可用的入口。
2. **审批**：v1 是否提供审批操作（`GET .../runs/{run_id}/approvals`、`POST .../approvals/{approval_id}`）？推荐：延后，与 native-run-workbench 的决定保持一致。
3. **知识库新建聊天**：Nexus 会话不挂载知识库。推荐：该路由直接跳转到 `/platform/creatChat`，不在 v1 支持知识库上下文。
4. **旧的 `/platform/native` 路径**：推荐：保留为重定向到新会话页，避免破坏已有书签。
5. **与 native-run-workbench 的关系**：本提案取代其「不改动 WeKnora 对话页」的约束，并合并其页面。推荐：在本提案确认后，把 native-run-workbench 标记为「已被替代」。

## 设计要点

- 状态以服务端为准：页面不保存权限、Run 终态或会话所有权；每次进入会话都重新读取。
- 所有 Run 相关事件按 `sequence` 去重并顺序渲染；断线后用 `Last-Event-ID` 续读，不重新提交。
- 模型输出按 WeKnora 的 Markdown 渲染管线处理，经 DOMPurify 净化，不直接注入 HTML。
- 视觉与交互以 WeKnora 为准，对照其 `views/chat/index.vue`、`components/Input-field.vue`、`views/chat/components/*`；偏离参考实现的地方须在 design.md 中列出理由。
- 使用 TDesign（与 `.codex/rules/frontend.md` 一致），不引入第二套组件库。

## 影响

- 修改：`router/index.ts`（占位路由替换为真实页面）、`stores/menu.ts`、`components/assistant/AssistantPanel.vue`、`views/chat/index.vue` 与相关组件、`views/native/*`（合并或删除）。
- 新增：会话适配层（Nexus 会话/Run 数据到 WeKnora 消息模型的映射）与对应单元测试。
- 文档：`apps/web/docs/design.md` 与 `apps/web/docs/requirements.md`（如存在）需同步；`docs/roadmap.md` 中对应进度条目需更新。
- 无后端改动。
