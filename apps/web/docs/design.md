# Web 设计

Vue 3、TypeScript、Element Plus、vue-router（history 模式）。外壳位于 `layouts/AppLayout.vue`：左侧 `layouts/AppSidebar.vue`（空间选择器、分组导航、当前空间的会话列表、用户区），右侧为路由页面。导航分组与旧 hash 页面映射位于 `router/navigation.ts`；路由定义位于 `router/index.ts`，`/#name` 旧链接由 `redirectLegacyHash` 改写为新路径。平台管理路由带 `requiresAdmin`，非管理员会被重定向到 `/chat`。登录不是路由：`App.vue` 在未登录时显示登录表单，错误信息来自 `/login?error=`。

当前空间保存在 `stores/workspace.ts`（localStorage 记住选择），对话、空间组织、角色、模型与 Native 页面都从它读取，不再各自放置空间下拉。会话 URL 为 `/chat/:sessionId`。部署需要为 history 模式配置回退到 `index.html`，否则直接打开深层路径会返回 404。

模型设置（设置 → 模型管理，`views/settings/NexusModelSettings.vue` 与 `NexusModelEditorDialog.vue`）沿用 WeKnora `ModelSettings.vue`、`ModelEditorDialog.vue` 的布局与样式（类型标签页与计数、搜索、卡片网格、添加卡片、居中编辑抽屉、底部测试连接），数据来自 `api/nexus-models.ts`（`/tenants/{id}/model-settings`）。WeKnora 的一条模型对应 Nexus 的「供应商 + 模型档案」：`views/settings/nexusModelCards.ts`（纯函数，有单元测试）把供应商下的模型展开为卡片，并决定保存时复用已有供应商还是先建供应商（失败重试复用已建供应商）。服务商下拉列出调用者可管理的供应商与「自定义（OpenAI 兼容接口）」；编辑时修改 Key 会轮换整个供应商的 Key，界面提示受影响的模型数。默认模型在卡片菜单中按作用域设置（个人默认；空间共享模型且调用者为管理员时还可设空间默认），卡片显示默认标签。Key 只在提交时发送，提交后清空，不写入浏览器存储。省略 WeKnora 的内置模型、模型目录、调试抽屉、用量对话框、Ollama 与云服务来源。

智能体（`/platform/agents`，`views/agent/NexusAgentList.vue` 与 `NexusAgentEditorModal.vue`）沿用 WeKnora `AgentList.vue`、`AgentEditorModal.vue` 的卡片网格、编辑弹窗外壳（`SettingsModalShell`）与分区样式，只保留 Nexus 支持的四个分区：基本信息、提示词、模型配置（对话模型、温度、最大生成 Token、思考强度、最大迭代次数、模型调用超时）、工具配置（按分组的内置工具目录，显示可写、需审批、只读标记；空间未启用的工具对管理员提供「启用」，对成员不可选）。WeKnora 的这两个组件与其知识库、组织、渠道等 store 深度耦合，因此按其模板与样式重写为 Nexus 版本，原文件保留但不再被路由引用。表单与 `AgentDraftInput` 的映射位于 `views/agent/nexusAgentForm.ts`（纯函数，有单元测试）：温度与思考强度写入 `budgets.generation`，最大 Token、迭代与超时写入执行预算，工具写入 `kind=tool` 绑定，保存时保留其他预算键与非工具绑定（如技能）。「保存」= 保存草稿后立即发布新版本；发布失败时保留草稿并提示原因。删除为归档：列表不再显示，已有会话可读但不能继续对话。卡片菜单「开始对话」跳转 `/platform/creatChat?agent=<已发布版本 ID>`，对话页据此预选智能体。

采用现有主色、语义 token、系统字体与 TDesign 组件；按钮与标签提供可读名称，窄屏卡片与操作换行。

主对话页（`/platform/creatChat` 新建对话；`/platform/chat/:chatid` 会话与运行，路由入口 `views/chat/NexusChatRoutePage.vue`，对话核心 `views/chat/NexusChatPage.vue` 由 `sessionId` 属性驱动）采用 WeKnora 对话页的布局与样式（960px 居中消息列、右侧用户气泡 `.user_msg`、左侧 Markdown 回答、底部 `.input-container` 输入框；欢迎态与 WeKnora `creatChat` 一致，标题与输入框一起垂直居中，侧边面板的窄布局不显示标题），数据只来自平台 Run API，不使用 WeKnora 对话接口。旧的 `/platform/native` 地址重定向到上述页面。`/platform/knowledge-bases/:kbId/creatChat` 同样重定向到新建对话页（会话不挂载知识库）。

- `api/native-run-types.ts`：Run、事件、会话等类型与运行时校验，不依赖网络或 i18n，便于测试。
- `api/native-runs.ts`：类型化的请求封装；事件流使用 `@microsoft/fetch-event-source`，携带与 axios 相同的认证头，并从 `Last-Event-ID` 续读。
- `composables/useNativeRun.ts`：提交（每次提交生成幂等键）、跟随事件流、刷新 Run 视图、告警确认、取消、追加提示、回答等待输入。断线后从已持有的序号续读，不重新提交 Run。
- `views/native/nativeRunState.ts`（被对话页复用）：纯状态规则（按序号去重、助手文本按轮拼接、工具调用汇总、各状态下允许的操作）。服务端仍是状态的事实来源，页面不保存权限或终态。
- `views/native/NativeWatchdogBanner.vue`（被对话页复用）：运行监督告警条，仅在服务端返回 `attention_required` 且 Run 未结束时显示；三个操作（继续等待、发送提示、取消）都由父组件调用接口后刷新。

模型输出目前按纯文本显示（保留换行，不解析 Markdown），因此不存在未净化 HTML 的注入路径。需要 Markdown 时应使用现有安全渲染组件。

- 侧栏会话列表（`components/menu.vue`）只读取平台会话 `listSessions`，展示「我的会话」一个分组；IM、嵌入渠道与 API 文件夹尚未迁移，不生成对应分组。平台会话暂无改名、置顶、清空与删除接口，因此会话菜单不提供这些操作（`SessionSidebarRow` 在无菜单项时隐藏更多按钮）。
- 对话页沿用 WeKnora 的以下界面：顶栏显示会话标题（`ChatHeader` 样式；标题取自会话列表，平台暂无改名、置顶、删除接口，因此没有菜单）；首次加载历史显示消息骨架屏；按间隔插入时间戳（`MessageTimestamp`）；用户消息直接使用 `usermsg.vue`（发送时间与复制，不传分叉、回滚）；助手回答悬停显示 `answer-toolbar`（目前只有复制）；已提交但尚无事件时显示等待指示；向上滚动后不再自动滚到底，并显示「回到底部」按钮。
- 对话页的运行过程与输入区复用 WeKnora 的 `AgentStreamDisplay.vue`（实时流，经 `utils/nexusAgentEvents.ts` 把 Run 事件适配为其事件流）与 `Input-field.vue`（`nexusMode`，屏蔽 WeKnora 专属加载与会话创建）；已持久化的消息仍用本页的气泡与 Markdown 渲染，未对齐 WeKnora 的 `botmsg.vue`。
- 助手面板（`components/assistant/AssistantPanel.vue`）的对话区直接使用 `NexusChatPage`（`compact` 窄布局，会话由 `assistant.sessionId` 决定，空值即欢迎态），历史列表读取平台会话，智能体取第一个已发布的智能体。页面上下文芯片、选区、访问级别选择与子智能体标签页已移除，平台 Run 接口不携带这些上下文；历史列表也不删除会话（平台暂无删除接口）。
- 尚未完成（见 `openspec/changes/2026-11-04-weknora-chat-dialog/tasks.md`）：完整 `vue-tsc` 与 `pnpm build` 未在受内存限制的环境中验证；浏览器用例未执行。
- 智能体与模型设置页（`2026-11-05-weknora-agent-tool-model-settings`）：已通过 SFC 编译、LESS 编译与针对新文件的 `vue-tsc` 检查；完整 `pnpm build` 与浏览器验证需在内存充足的环境执行。
