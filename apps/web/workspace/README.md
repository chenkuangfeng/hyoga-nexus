# @nexus-web/workspace

员工工作台 Vite 应用，包含主入口 `index.html` 和独立嵌入入口 `embed.html`。

`src/` 保留迁移前的页面、组件、路由和工作台状态；公共 API、认证、语言和基础主题逻辑引用 `@nexus-web/core`。企业化的导航、资源归属、单智能体模式及窄屏调整仍按 E2.2–E2.4 实施。

在 `apps/web/` 运行 `pnpm dev:workspace`（5173）、`pnpm --filter @nexus-web/workspace build` 或 `pnpm --filter @nexus-web/workspace test`。产物为 `workspace/dist`。开发服务保留 `/embed/:channelId` 到嵌入 HTML 的回退和 API WebSocket 代理。
