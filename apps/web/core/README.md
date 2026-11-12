# @nexus-web/core

两个 Web 应用共用的源码包，不单独构建或部署。

- `src/api/`：类型化接口与请求契约。
- `src/stores/`：认证、企业身份、资源缓存与刷新排序；应用入口来自服务端成员身份的 `entries`。
- `src/composables/`、`src/utils/`：主题、字体、请求与令牌刷新等基础逻辑。
- `src/i18n/`：公共语言资源与审计、扫描工具。
- `src/views/auth/`：公共登录与改密组件；自助注册只创建企业，邀请注册加入已有企业。
- `src/components/NotFound.vue`：两个应用共用的未知页面提示。

应用经 `@nexus-web/core/...` 导入源码。Vue、TDesign、Pinia、vue-router 与 vue-i18n 使用 peerDependencies，共用 catalog 版本。公共包不得反向导入两个应用，`pnpm test` 检查该边界。

在 `apps/web/` 运行 `pnpm --filter @nexus-web/core type-check` 或 `pnpm --filter @nexus-web/core test`。编辑器、公共组件和样式的后续抽取见企业化提案 E2.3。
