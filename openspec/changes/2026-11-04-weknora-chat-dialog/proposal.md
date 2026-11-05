# 严格参考 WeKnora 实现聊天对话框

## 状态

已确认（2026-11-04）：五项决定全部采用推荐方案。实施状态见 tasks.md。

**范围调整（2026-11-05，已确认：待确认项 1–4 全部采用推荐方案）**：用户要求「完全按照 WeKnora 的对话框界面复制，缺少的功能先占位」，取代决定 1 的「隐藏」。见文末「范围调整」一节。

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

## 已确认的决定（全部采用推荐方案）

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

## 范围调整（2026-11-05，已确认）

### 原因

用户要求对话框界面完全按 WeKnora 复制，平台缺少的功能先保留入口作为占位。这取代已确认决定 1（隐藏不支持的入口）；决定 2–5 不变，除非下面的待确认项另有选择。

### 范围

1. **结构与组件**：对话页按 WeKnora `views/chat/index.vue` 的结构重写（`chat-topbar`、`chat_thread`、`chat_scroll_box`、`msg_list`、`chat_composer`、`chat_overlays`），样式原样复制。能直接复用的原组件直接使用：`botmsg.vue`（只依赖本地界面状态）、`usermsg.vue`、`AgentStreamDisplay.vue`、`ChatQuestionMinimap.vue`、`PendingPromptDock.vue`、`MessageTimestamp.vue`。调用 WeKnora 接口的组件（`ChatHeader.vue`、`creatChat.vue`、`AskUserCard.vue`、`ToolApprovalCard.vue`、`FollowUpSuggestions.vue`）按原模板与样式复制为 Nexus 版本，接入平台接口或改为占位。
2. **历史回答**：每条助手消息用 `botmsg.vue` 渲染，并带上该轮 Run 的事件时间线（思考、工具调用、结果）。数据来自已有的 `GET .../runs/{run_id}/events`，不新增接口。
3. **有平台能力的部分接入真实数据**：会话标题、发送、取消、追加指令、等待输入（`AskUserCard` 样式）、运行告警、复制，以及待确认项 2 的审批。
4. **缺后端的部分保留入口作为占位**，点击后统一提示「该功能暂未开放」（待确认项 1）：
   - 顶栏：改名、置顶、复制为 Markdown（可在前端实现，见下）、删除会话、查看授权、沙箱面板开关。
   - 欢迎页：推荐问题区（显示占位卡片）、项目目录选择。
   - 消息：分叉、回滚、问助手、加入知识库、请求详情、产物抽屉、引用浮层、追问建议。
   - 输入框：模式切换、知识库、联网搜索、本地浏览器、模型选择、思考强度、图片与附件上传、@ 引用。
   - 侧边与弹层：引用抽屉、附件预览、沙箱侧面板、浏览器任务预览、后台任务。
   - 子智能体标签页：没有子运行数据时不出现（属于数据驱动的展示，不是入口）。
5. **不改后端**：所有占位只在前端实现；不新增或修改接口、权限与持久化模型。

### 已确认的决定（全部采用推荐方案）

1. **占位方式**：推荐「入口照常显示、可点击，点击后提示『该功能暂未开放』」，与 WeKnora 外观完全一致；备选「入口显示但置灰，悬停提示『规划中』」。
2. **审批卡**：平台已有审批接口（`GET .../runs/{run_id}/approvals`、`POST .../approvals/{approval_id}`）。推荐：本次接入 `ToolApprovalCard`，用户可批准或拒绝（取代决定 2 的「延后」）；备选：只显示卡片，按钮作为占位。
3. **历史时间线的加载**：推荐打开会话时并发读取各轮 Run 的事件（最多同时 4 个请求），完整还原时间线；备选：只在用户展开某条回答时再读取。
4. **复制为 Markdown**：这个功能只需要前端拼接已有消息，推荐直接实现，不作为占位。

### 验收

- 与 WeKnora 对话页、新建对话页逐区比对，布局、组件与样式一致；所有 WeKnora 入口都在。
- 占位入口点击后只提示，不发出任何 WeKnora 接口请求（以测试断言请求路径）。
- 历史回答显示该轮的思考与工具时间线；运行中与历史回答使用同一组件。
- 中英文文案齐全；样式守卫、语言包一致性与既有单元测试通过。
