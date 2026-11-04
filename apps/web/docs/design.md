# Web 设计

Vue 3、TypeScript、Element Plus、vue-router（history 模式）。外壳位于 `layouts/AppLayout.vue`：左侧 `layouts/AppSidebar.vue`（空间选择器、分组导航、当前空间的会话列表、用户区），右侧为路由页面。导航分组与旧 hash 页面映射位于 `router/navigation.ts`；路由定义位于 `router/index.ts`，`/#name` 旧链接由 `redirectLegacyHash` 改写为新路径。平台管理路由带 `requiresAdmin`，非管理员会被重定向到 `/chat`。登录不是路由：`App.vue` 在未登录时显示登录表单，错误信息来自 `/login?error=`。

当前空间保存在 `stores/workspace.ts`（localStorage 记住选择），对话、空间组织、角色、模型与 Native 页面都从它读取，不再各自放置空间下拉。会话 URL 为 `/chat/:sessionId`。部署需要为 history 模式配置回退到 `index.html`，否则直接打开深层路径会返回 404。

`views/settings/ModelSettingsView.vue` 组合供应商卡片、模型列表、默认模型选择和创建智能体表单；`composables/useModelSettings.ts` 管理请求、模态框、取消查询、防重复提交与秘密清理；`api/modelSettings.ts` 进行响应校验和请求封装；DTO 位于 `types/modelSettings.ts`。

采用现有绿色主色、语义 token、系统字体与表单风格。设计技能查询的营销布局不适用本设置页，沿用现有产品布局；表单交互使用 Element Plus，未新增另一套表单依赖。按钮/标签提供可读名称，状态区播报结果，窄屏卡片与操作换行。

浏览器用例位于 `tests/web/model-settings.mjs`，运行在 API 夹具上；不能代替真实部署端到端验收。

Native 运行工作台（`/platform/native`，会话列表与新建；`/platform/native/sessions/:sessionId`，对话与运行）只调用平台 Run API，不使用 WeKnora 对话接口。

- `api/native-run-types.ts`：Run、事件、会话等类型与运行时校验，不依赖网络或 i18n，便于测试。
- `api/native-runs.ts`：类型化的请求封装；事件流使用 `@microsoft/fetch-event-source`，携带与 axios 相同的认证头，并从 `Last-Event-ID` 续读。
- `composables/useNativeRun.ts`：提交（每次提交生成幂等键）、跟随事件流、刷新 Run 视图、告警确认、取消、追加提示、回答等待输入。断线后从已持有的序号续读，不重新提交 Run。
- `views/native/nativeRunState.ts`：纯状态规则（按序号去重、助手文本按轮拼接、工具调用汇总、各状态下允许的操作）。服务端仍是状态的事实来源，页面不保存权限或终态。
- `views/native/NativeWatchdogBanner.vue`：运行监督告警条，仅在服务端返回 `attention_required` 且 Run 未结束时显示；三个操作（继续等待、发送提示、取消）都由父组件调用接口后刷新。

模型输出目前按纯文本显示（保留换行，不解析 Markdown），因此不存在未净化 HTML 的注入路径。需要 Markdown 时应使用现有安全渲染组件。
