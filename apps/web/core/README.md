# @nexus-web/core

两个 Web 应用共用的源码包，不单独构建或部署。

- `src/api/`：类型化接口与请求契约；`enterprise-admin.ts` 提供企业策略、部门选项校验与差异补丁；`enterprise-members.ts` 校验成员、人员/链接邀请及加入申请审批的真实契约；`enterprise-organizations.ts` 校验单根无环组织树、节点与成员归属回执，并提供当前企业内的节点和归属操作；`enterprise-knowledge.ts` 校验企业知识库目录、内容管理员、部门/成员读取受众和按企业作用域删除；`enterprise-knowledge-content.ts` 校验企业文档、FAQ 条目和 Wiki 页面内容接口。
- `src/stores/`：认证、企业身份、资源缓存与刷新排序；应用入口来自服务端成员身份的 `entries`。
- `src/composables/`、`src/utils/`：主题、字体、请求与令牌刷新等基础逻辑；剪贴板统一提供现代 API 和 HTTP 环境降级；离线图标初始化阻止外网 CDN 请求，配合两应用本地 SVG sprite。
- `src/components/SettingsModalShell.vue`、`SettingsRow.vue`：设置页与管理端共用的导航外壳和标准设置行。
- `src/components/knowledge-editor/`：工作台和管理后台共用的完整知识库编辑器与设置组件；宿主负责导航，知识库管理端受众控制由 `api/enterprise-knowledge.ts` 提供类型化契约。
- `src/styles/`：原设置页主题、TDesign 全局覆盖，以及设置标题/行/表格 mixin；工作台原 CSS 路径转导入这些公共实现。
- `src/i18n/`：公共语言资源与审计、扫描工具。
- `src/views/auth/`：公共登录与改密组件；自助注册只创建企业，邀请注册加入已有企业。
- `src/components/IMChannelPanel.vue`：智能体 IM 渠道面板，遵循维护权限、归属与企业策略，二维码在本地生成；接口封装在 `api/enterprise-connections.ts`。
- `src/components/NotFound.vue`：两个应用共用的未知页面提示。

应用经 `@nexus-web/core/...` 导入源码。Vue、TDesign、Pinia、vue-router 与 vue-i18n 使用 peerDependencies，共用 catalog 版本。公共包不得反向导入两个应用，`pnpm test` 检查该边界。

在 `apps/web/` 运行 `pnpm --filter @nexus-web/core type-check` 或 `pnpm --filter @nexus-web/core test`。编辑器、公共组件和样式的后续抽取见企业化提案 E2.3。
