# Web 设计

Vue 3、TypeScript、Element Plus、vue-router（history 模式）。外壳位于 `layouts/AppLayout.vue`：左侧 `layouts/AppSidebar.vue`（空间选择器、分组导航、当前空间的会话列表、用户区），右侧为路由页面。导航分组与旧 hash 页面映射位于 `router/navigation.ts`；路由定义位于 `router/index.ts`，`/#name` 旧链接由 `redirectLegacyHash` 改写为新路径。平台管理路由带 `requiresAdmin`，非管理员会被重定向到 `/chat`。登录不是路由：`App.vue` 在未登录时显示登录表单，错误信息来自 `/login?error=`。

当前空间保存在 `stores/workspace.ts`（localStorage 记住选择），对话、空间组织、角色、模型与 Native 页面都从它读取，不再各自放置空间下拉。会话 URL 为 `/chat/:sessionId`。部署需要为 history 模式配置回退到 `index.html`，否则直接打开深层路径会返回 404。

`views/settings/ModelSettingsView.vue` 组合供应商卡片、模型列表、默认模型选择和创建智能体表单；`composables/useModelSettings.ts` 管理请求、模态框、取消查询、防重复提交与秘密清理；`api/modelSettings.ts` 进行响应校验和请求封装；DTO 位于 `types/modelSettings.ts`。

采用现有绿色主色、语义 token、系统字体与表单风格。设计技能查询的营销布局不适用本设置页，沿用现有产品布局；表单交互使用 Element Plus，未新增另一套表单依赖。按钮/标签提供可读名称，状态区播报结果，窄屏卡片与操作换行。

浏览器用例位于 `tests/web/model-settings.mjs`，运行在 API 夹具上；不能代替真实部署端到端验收。

Native 接口统一封装在 `api/native.ts`，设置页位于 `views/settings/NativeSettingsView.vue`，运行控制和模型分支分别由 `RuntimeControls.vue`、`ModelBranchControls.vue` 负责。异步加载清理、错误反馈和禁用状态由组件管理；服务端仍是授权与运行状态的事实来源。候选项仅填写回答框，由用户显式提交；追加指令携带幂等键，不新建 Run。
