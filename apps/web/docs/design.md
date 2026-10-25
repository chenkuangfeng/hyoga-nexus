# Web 设计

Vue 3、TypeScript、Element Plus；主导航通过现有 hash 机制切换 `#chat`、`#settings` 和 `#overview`。

`views/settings/ModelSettingsView.vue` 组合供应商卡片、模型列表、默认模型选择和创建智能体表单；`composables/useModelSettings.ts` 管理请求、模态框、取消查询、防重复提交与秘密清理；`api/modelSettings.ts` 进行响应校验和请求封装；DTO 位于 `types/modelSettings.ts`。

采用现有绿色主色、语义 token、系统字体与表单风格。设计技能查询的营销布局不适用本设置页，沿用现有产品布局；表单交互使用 Element Plus，未新增另一套表单依赖。按钮/标签提供可读名称，状态区播报结果，窄屏卡片与操作换行。

浏览器用例位于 `tests/web/model-settings.mjs`，运行在 API 夹具上；不能代替真实部署端到端验收。
