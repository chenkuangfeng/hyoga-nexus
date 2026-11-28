# @nexus-web/workspace

员工工作台 Vite 应用，主入口为 `index.html`，另有独立嵌入入口 `embed.html`。公共认证、API、语言和主题引用 `@nexus-web/core`；工作台与 `/enterprise/` 管理后台独立构建，两个应用不互相导入。

在 `apps/web/` 执行 `pnpm dev:workspace`（5173）、`pnpm --filter @nexus-web/workspace build` 或 `pnpm --filter @nexus-web/workspace test`。产物为 `workspace/dist`。开发服务保留 `/embed/:channelId` 到嵌入 HTML 的回退和 API WebSocket 代理。

## 工作台功能

- 主菜单只有新对话、知识库、智能体；会话历史继续位于侧栏。
- 知识库只浏览可读目录与维护已授权内容，不提供创建、复制、删除库、共享或资源配置。普通建库 HTTP 入口返回 403；企业管理员在管理应用创建企业库，点名的维护员仍可维护文档、分块、FAQ、Wiki 等内容。
- 智能体目录只提供查看和使用已发布版本；创建、编辑、复制、归档、受众和渠道管理均位于管理应用。
- 会话页顶部仅提供左对齐的对话、轨迹、产物标签。轨迹表按 Run 分组，逐轮显示用户、助手和工具调用/结果活动，调用与结果按 call id 配对；列表固定活动、内容、Token 列并省略过长摘要，助手活动可查看关联的模型请求快照和实际 Token 或估算。顶部统计方块显示请求次数、会话累计 Token 和缓存命中量。独立的 `run_trajectory_records` 表记录模型请求/响应快照，轨迹列表不从 Run 事件构建。产物集中在产物标签预览和下载，不再占用右侧栏。切换会话清空原产物，下载继续由服务端检查会话权限并审计。
- 账户设置始终弹出，只保留常规设置、用户信息、我的记忆。空间长期记忆由管理端企业空间维护。旧工具箱、自动化、产物库、共享空间和渠道地址回到新对话，不加载原管理页面；已迁移的 parser/storage/vectorstore/members/org-structure 设置书签仅显示显式管理链接，不读取治理配置。

目录卡片沿用 WeKnora 固定版的资源卡片结构；API、授权和作用域使用 Nexus 契约。目录支持搜索、加载失败重试和资源变更通知刷新，身份变化及卸载丢弃旧响应。

## 身份与入口

注册只提供企业注册，邀请注册加入已有企业。临时密码账号先完成改密才能进入工作台。普通令牌恢复、OIDC 与部署允许的开发登录使用统一认证 API。当前企业成员身份、只读企业信息和本人退出位于用户信息；owner 须先转移所有权。切换企业和退出时清理旧身份相关数据。

Wails、桌面自动登录、地址恢复、平台管理入口、浮动助手和企业治理导航已移除。聊天工具结果、审批、引用与服务端持久事件契约保持一致；不会通过移除菜单改变运行中任务。

## 验证与文档

在 Web 根目录执行 `pnpm type-check`、`pnpm build`、`pnpm test`、`pnpm test:browser:workspace`。小内存机器按顺序执行。浏览器用例明确模拟 API，不替代真实服务验收。

- [Web 需求](../docs/requirements.md)
- [Web 设计](../docs/design.md)
- [浏览器回归说明](../e2e/README.md)
