# @nexus-web/workspace

员工工作台 Vite 应用，包含主入口 `index.html` 和独立嵌入入口 `embed.html`。

`src/` 提供页面、组件、路由和工作台状态；公共 API、认证、语言和基础主题逻辑引用 `@nexus-web/core`。企业化的导航、资源归属、单智能体模式及窄屏调整仍按 E2.2–E2.4 实施。

在 `apps/web/` 运行 `pnpm dev:workspace`（5173）、`pnpm --filter @nexus-web/workspace build` 或 `pnpm --filter @nexus-web/workspace test`。产物为 `workspace/dist`。开发服务保留 `/embed/:channelId` 到嵌入 HTML 的回退和 API WebSocket 代理。

平台管理页面与路由、Wails 绑定、桌面自动登录和地址恢复已移除。旧平台管理地址显示公共 404；旧设置查询归一到常规设置。注册页只提供企业注册，邀请注册加入已有企业。改密入口要求认证，临时密码账号先完成改密才能进入工作台。普通令牌恢复与部署允许的开发登录继续使用统一认证 API。

旧浮动助手的面板、设置、侧栏/命令入口和文档/Wiki 唤出动作已移除。普通聊天仍支持工具卡片与表单草稿跳转；草稿在内存中一次性消费，切换账号或企业时清空。资源变更后的列表与文档刷新仍使用公共通知契约。
