# Web 设计

Vue 3、TypeScript、TDesign、Pinia、vue-router（history 模式）、vue-i18n 与 Vite。`apps/web` 是 pnpm workspace，公共包与两个应用的边界见下文。下文页面、组件与业务状态路径相对 `workspace/src`，API、认证与语言路径相对 `core/src`。

员工工作台外壳为 `views/platform/index.vue`，左侧为 `components/menu.vue`，右侧为业务路由与共享的设置、上传任务、命令面板等组件。路由在 `workspace/src/router/index.ts`，登录入口为 `/login`，会话地址为 `/platform/chat/:chatid`。认证与当前企业由 `core/src/stores/auth.ts` 统一管理，布局偏好由工作台 `stores/ui.ts` 管理。平台管理路由已删除，未知地址使用公共 404 页面。部署需为两个应用分别配置 history 回退。

模型设置（设置 → 模型管理，`views/settings/NexusModelSettings.vue` 与 `NexusModelEditorDialog.vue`）沿用 WeKnora `ModelSettings.vue`、`ModelEditorDialog.vue` 的布局与样式（类型标签页与计数、搜索、卡片网格、添加卡片、居中编辑抽屉、底部测试连接），数据来自 `api/nexus-models.ts`（`/tenants/{id}/model-settings`）。WeKnora 的一条模型对应 Nexus 的「供应商 + 模型档案」：`views/settings/nexusModelCards.ts`（纯函数，有单元测试）把供应商下的模型展开为卡片，并决定保存时复用已有供应商还是先建供应商（失败重试复用已建供应商）。服务商下拉列出调用者可管理的供应商与「自定义（OpenAI 兼容接口）」；编辑时修改 Key 会轮换整个供应商的 Key，界面提示受影响的模型数。默认模型在卡片菜单中按作用域设置（个人默认；空间共享模型且调用者为管理员时还可设空间默认），卡片显示默认标签。Key 只在提交时发送，提交后清空，不写入浏览器存储。省略 WeKnora 的内置模型、模型目录、调试抽屉、用量对话框、Ollama 与云服务来源。

智能体（`/platform/agents`，`views/agent/NexusAgentList.vue` 与 `NexusAgentEditorModal.vue`）沿用 WeKnora `AgentList.vue`、`AgentEditorModal.vue` 的卡片网格、编辑弹窗外壳（`SettingsModalShell`）与分区样式，只保留 Nexus 支持的四个分区：基本信息、提示词、模型配置（对话模型、温度、最大生成 Token、思考强度、最大迭代次数、模型调用超时）、工具配置（按分组的内置工具目录，显示可写、需审批、只读标记；空间未启用的工具对管理员提供「启用」，对成员不可选）。WeKnora 的这两个组件与其知识库、组织、渠道等 store 深度耦合，因此按其模板与样式重写为 Nexus 版本，原文件保留但不再被路由引用。表单与 `AgentDraftInput` 的映射位于 `views/agent/nexusAgentForm.ts`（纯函数，有单元测试）：温度与思考强度写入 `budgets.generation`，最大 Token、迭代与超时写入执行预算，工具写入 `kind=tool` 绑定，保存时保留其他预算键与非工具绑定（如技能）。「保存」= 保存草稿后立即发布新版本；发布失败时保留草稿并提示原因。删除为归档：列表不再显示，已有会话可读但不能继续对话。卡片菜单「开始对话」跳转 `/platform/creatChat?agent=<已发布版本 ID>`，对话页据此预选智能体。

采用现有主色、语义 token、系统字体与 TDesign 组件；按钮与标签提供可读名称，窄屏卡片与操作换行。

主对话页（`/platform/creatChat` 新建对话；`/platform/chat/:chatid` 会话与运行，路由入口 `views/chat/NexusChatRoutePage.vue`，对话核心 `views/chat/NexusChatPage.vue` 由 `sessionId` 属性驱动）按 WeKnora 复制：会话态的结构与样式取自 `views/chat/index.vue`（`chat-topbar`、`chat_thread`、`chat_scroll_box`、`msg_list`、悬浮的 `chat_composer`、`chat_overlays`），欢迎态取自 `views/creatChat/creatChat.vue`（标题、推荐问题区、输入框垂直居中）；侧边助手面板（`compact`）使用 WeKnora 的嵌入布局。数据只来自平台 Run API，不调用 WeKnora 对话接口。旧的 `/platform/native` 地址重定向到上述页面。`/platform/knowledge-bases/:kbId/creatChat` 同样重定向到新建对话页（会话不挂载知识库）。

- `api/native-run-types.ts`：Run、事件、会话等类型与运行时校验，不依赖网络或 i18n，便于测试。
- `api/native-runs.ts`：类型化的请求封装；事件流使用 `@microsoft/fetch-event-source`，携带与 axios 相同的认证头，并从 `Last-Event-ID` 续读。
- `composables/useNativeRun.ts`：提交（每次提交生成幂等键）、跟随事件流、刷新 Run 视图、告警确认、取消、追加提示、回答等待输入。断线后从已持有的序号续读，不重新提交 Run。
- `views/native/nativeRunState.ts`（被对话页复用）：纯状态规则（按序号去重、助手文本按轮拼接、工具调用汇总、各状态下允许的操作）。服务端仍是状态的事实来源，页面不保存权限或终态。
- `views/native/NativeWatchdogBanner.vue`（被对话页复用）：运行监督告警条，仅在服务端返回 `attention_required` 且 Run 未结束时显示；三个操作（继续等待、发送提示、取消）都由父组件调用接口后刷新。

模型输出由 WeKnora 的 Markdown 管线渲染（`botmsg.vue` 与 `AgentStreamDisplay.vue`），输出经 DOMPurify 净化。

- 侧栏会话列表（`components/menu.vue`）只读取平台会话 `listSessions`，展示「我的会话」一个分组；IM、嵌入渠道与 API 文件夹尚未迁移，不生成对应分组。平台会话暂无改名、置顶、清空与删除接口，因此会话菜单不提供这些操作（`SessionSidebarRow` 在无菜单项时隐藏更多按钮）。
- 复用的 WeKnora 组件：`usermsg.vue`、`botmsg.vue`（含 `AgentStreamDisplay` 时间线与回答工具栏）、`MessageTimestamp`、`ChatQuestionMinimap`、`PendingPromptDock`、`ToolApprovalCard`、`AskUserCard`、`Input-field.vue`（`nexusMode`）。调用 WeKnora 接口的 `ChatHeader.vue` 按原模板复制为 `components/NexusChatHeader.vue`。
- 数据适配：`utils/nexusChatTranscript.ts` 把平台消息按 Run 分组为 WeKnora 行（一条用户消息 + 一条助手回答），历史回答的时间线由该 Run 的事件重建（打开会话时以最多 4 个并发读取 `GET .../runs/{id}/events`；读取失败时回退为正文）。`utils/nexusAgentEvents.ts` 把 Run 事件映射为 `agentEventStream`：文本、工具调用、`approval.*` → `tool_approval_required`、`input.*` → `agent_prompt_required`（ask_user）。审批参数只经 `GET .../approvals` 取得。
- 运行操作：`composables/nexusChatActions.ts` 由对话页提供；`ToolApprovalCard` 与 `AskUserCard` 检测到它时改调平台审批与回答接口（审批后 `useNativeRun.resume()` 继续跟随），否则保持 WeKnora 原行为。
- 占位：平台尚无后端的入口照常显示，点击统一提示「该功能暂未开放」——顶栏改名（含双击标题）、查看授权、删除会话、沙箱面板；欢迎页推荐问题与刷新；消息分叉、回滚、问助手、加入知识库、产物；输入框本地浏览器、联网搜索、图片与附件上传、@ 引用、模型与思考强度。「复制为 Markdown」在前端实现。数据驱动的区域（追问建议、子智能体标签页、引用与附件抽屉、浏览器任务预览、后台任务）在没有数据时与 WeKnora 一样不出现。
- 智能体选择与 WeKnora 一致：输入框左侧的 `agent-mode-btn` 打开 `components/NexusAgentSelector.vue`（按 WeKnora `AgentSelector.vue` 的模板、定位与样式复制，只列平台已发布的智能体，归入「自定义智能体」；不读取 WeKnora 的 store 与接口）。会话已绑定智能体，会话内点击该按钮为占位。
- 已去掉 Nexus 自加的元素：运行状态标签、运行停滞告警条（`NativeWatchdogBanner.vue` 保留但不再挂载）、失败与排队提示行。运行失败时与 WeKnora 处理运行级错误相同：错误说明作为回答写入时间线，并弹出错误提示。因此对话页目前没有「继续等待 / 发送提示」与排队位置的入口；取消用输入框的停止按钮，追加指令用运行中的发送。
- 与 WeKnora 仍不同之处：欢迎页不显示宿主沙箱的项目目录条（WeKnora 仅桌面端显示）。
- 助手面板（`components/assistant/AssistantPanel.vue`）的对话区直接使用 `NexusChatPage`（`compact` 窄布局，会话由 `assistant.sessionId` 决定，空值即欢迎态），历史列表读取平台会话，智能体取第一个已发布的智能体。页面上下文芯片、选区、访问级别选择与子智能体标签页已移除，平台 Run 接口不携带这些上下文；历史列表也不删除会话（平台暂无删除接口）。
- 尚未完成（见 `openspec/changes/2026-11-04-weknora-chat-dialog/tasks.md`）：完整 `vue-tsc` 与 `pnpm build` 未在受内存限制的环境中验证；浏览器用例未执行。
- 智能体与模型设置页（`2026-11-05-weknora-agent-tool-model-settings`）：已通过 SFC 编译、LESS 编译与针对新文件的 `vue-tsc` 检查；完整 `pnpm build` 与浏览器验证需在内存充足的环境执行。

## pnpm workspace

`core`、`workspace`、`admin` 使用唯一锁文件与 `pnpm-workspace.yaml` 的 catalog。`tsconfig.base.json` 开启严格类型检查；两个 Vite 配置调用根 `createWebConfig` 工厂，统一 API 代理、PDF WASM 复制和依赖拆包。工作台保留主页面和 embed 两个入口，管理应用 base 为 `/admin/`。

原 `src` 和 `public` 分别移入 `workspace/src`、`workspace/public`；公共 API 的传递依赖闭包抽到 `core/src`，公共包不引用应用。应用用 `@nexus-web/core/...` 访问公共源码，Vite 排除其依赖预构建并统一 Vue 实例。登录、改密保留原有组件与流程，管理应用登录后进入本应用首页。

`stores/entries.ts` 按当前企业查询应用入口；不存在的企业、缺失 entries 的旧缓存返回空入口。`scripts/check-boundaries.ts` 检查静态导入、导出和动态导入的方向。平台管理页面、路由和专用模型目录适配器已删除，Wails 与自动初始化入口已移除；工作台仍包含待移除的助手及旧集成，管理业务页、共用编辑器、样式和双应用浏览器验收仍待 E2 后续任务；尚未满足“工作台产物不含管理后台代码”的最终门禁。

认证恢复只使用已有令牌，不尝试桌面自动初始化。注册表单按是否持有邀请令牌分流：自助注册发送企业名称与编码，邀请注册只发送邀请与账号字段。两应用共用 404 页面，已删除的平台管理路由不再挂载应用页面；旧设置参数归一到 `general` 并移除旧 `panel` 参数。工作台改密路由先经过认证，临时密码账号先改密，避免初始化豁免绕过认证。

管理应用只承载本应用的路由；邀请与无企业身份的开户入口以原始 `fullPath` 转交员工应用，保留邀请参数。两个应用的未知路径使用共用 404 组件。
