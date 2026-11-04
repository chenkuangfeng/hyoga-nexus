# Web 设计

Vue 3、TypeScript、Element Plus、vue-router（history 模式）。外壳位于 `layouts/AppLayout.vue`：左侧 `layouts/AppSidebar.vue`（空间选择器、分组导航、当前空间的会话列表、用户区），右侧为路由页面。导航分组与旧 hash 页面映射位于 `router/navigation.ts`；路由定义位于 `router/index.ts`，`/#name` 旧链接由 `redirectLegacyHash` 改写为新路径。平台管理路由带 `requiresAdmin`，非管理员会被重定向到 `/chat`。登录不是路由：`App.vue` 在未登录时显示登录表单，错误信息来自 `/login?error=`。

当前空间保存在 `stores/workspace.ts`（localStorage 记住选择），对话、空间组织、角色、模型与 Native 页面都从它读取，不再各自放置空间下拉。会话 URL 为 `/chat/:sessionId`。部署需要为 history 模式配置回退到 `index.html`，否则直接打开深层路径会返回 404。

`views/settings/ModelSettingsView.vue` 组合供应商卡片、模型列表、默认模型选择和创建智能体表单；`composables/useModelSettings.ts` 管理请求、模态框、取消查询、防重复提交与秘密清理；`api/modelSettings.ts` 进行响应校验和请求封装；DTO 位于 `types/modelSettings.ts`。

采用现有绿色主色、语义 token、系统字体与表单风格。设计技能查询的营销布局不适用本设置页，沿用现有产品布局；表单交互使用 Element Plus，未新增另一套表单依赖。按钮/标签提供可读名称，状态区播报结果，窄屏卡片与操作换行。

浏览器用例位于 `tests/web/model-settings.mjs`，运行在 API 夹具上；不能代替真实部署端到端验收。

主对话页（`/platform/creatChat` 新建对话；`/platform/chat/:chatid` 会话与运行，路由入口 `views/chat/NexusChatRoutePage.vue`，对话核心 `views/chat/NexusChatPage.vue` 由 `sessionId` 属性驱动）采用 WeKnora 对话页的布局与样式（960px 居中消息列、右侧用户气泡 `.user_msg`、左侧 Markdown 回答、底部 `.input-container` 输入框；欢迎态与 WeKnora 一致，只显示底部输入框），数据只来自平台 Run API，不使用 WeKnora 对话接口。旧的 `/platform/native` 地址重定向到上述页面。`/platform/knowledge-bases/:kbId/creatChat` 同样重定向到新建对话页（会话不挂载知识库）。

- `api/native-run-types.ts`：Run、事件、会话等类型与运行时校验，不依赖网络或 i18n，便于测试。
- `api/native-runs.ts`：类型化的请求封装；事件流使用 `@microsoft/fetch-event-source`，携带与 axios 相同的认证头，并从 `Last-Event-ID` 续读。
- `composables/useNativeRun.ts`：提交（每次提交生成幂等键）、跟随事件流、刷新 Run 视图、告警确认、取消、追加提示、回答等待输入。断线后从已持有的序号续读，不重新提交 Run。
- `views/native/nativeRunState.ts`（被对话页复用）：纯状态规则（按序号去重、助手文本按轮拼接、工具调用汇总、各状态下允许的操作）。服务端仍是状态的事实来源，页面不保存权限或终态。
- `views/native/NativeWatchdogBanner.vue`（被对话页复用）：运行监督告警条，仅在服务端返回 `attention_required` 且 Run 未结束时显示；三个操作（继续等待、发送提示、取消）都由父组件调用接口后刷新。

模型输出目前按纯文本显示（保留换行，不解析 Markdown），因此不存在未净化 HTML 的注入路径。需要 Markdown 时应使用现有安全渲染组件。

- 侧栏会话列表（`components/menu.vue`）只读取平台会话 `listSessions`，展示「我的会话」一个分组；IM、嵌入渠道与 API 文件夹尚未迁移，不生成对应分组。平台会话暂无改名、置顶、清空与删除接口，因此会话菜单不提供这些操作（`SessionSidebarRow` 在无菜单项时隐藏更多按钮）。
- 对话页的运行过程与输入区复用 WeKnora 的 `AgentStreamDisplay.vue`（实时流，经 `utils/nexusAgentEvents.ts` 把 Run 事件适配为其事件流）与 `Input-field.vue`（`nexusMode`，屏蔽 WeKnora 专属加载与会话创建）；已持久化的消息仍用本页的气泡与 Markdown 渲染，未对齐 WeKnora 的 `botmsg.vue`。
- 助手面板（`components/assistant/AssistantPanel.vue`）的对话区直接使用 `NexusChatPage`（`compact` 窄布局，会话由 `assistant.sessionId` 决定，空值即欢迎态），历史列表读取平台会话，智能体取第一个已发布的智能体。页面上下文芯片、选区、访问级别选择与子智能体标签页已移除，平台 Run 接口不携带这些上下文；历史列表也不删除会话（平台暂无删除接口）。
- 尚未完成（见 `openspec/changes/2026-11-04-weknora-chat-dialog/tasks.md`）：完整 `vue-tsc` 与 `pnpm build` 未在受内存限制的环境中验证；浏览器用例未执行。
