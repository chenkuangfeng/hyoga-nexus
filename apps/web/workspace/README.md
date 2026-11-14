# @nexus-web/workspace

员工工作台 Vite 应用，包含主入口 `index.html` 和独立嵌入入口 `embed.html`。

`src/` 提供页面、组件、路由和工作台状态；公共 API、认证、语言和基础主题逻辑引用 `@nexus-web/core`。企业化的导航、资源归属、单智能体模式及窄屏调整仍按 E2.2–E2.4 实施。

在 `apps/web/` 运行 `pnpm dev:workspace`（5173）、`pnpm --filter @nexus-web/workspace build` 或 `pnpm --filter @nexus-web/workspace test`。产物为 `workspace/dist`。开发服务保留 `/embed/:channelId` 到嵌入 HTML 的回退和 API WebSocket 代理。

平台管理页面与路由、Wails 绑定、桌面自动登录和地址恢复已移除。旧平台管理地址显示公共 404；旧设置查询归一到常规设置。注册页只提供企业注册，邀请注册加入已有企业。改密入口要求认证，临时密码账号先完成改密才能进入工作台。普通令牌恢复与部署允许的开发登录继续使用统一认证 API。

旧浮动助手的面板、设置、侧栏/命令入口和文档/Wiki 唤出动作已移除。普通聊天仍支持工具卡片与表单草稿跳转；草稿在内存中一次性消费，切换账号或企业时清空。资源变更后的列表与文档刷新仍使用公共通知契约。

智能体卡片的「渠道」进入 `/platform/agents/:agentId/channels`；IM 管理由公共组件承载，embed 后端尚未接入。账户设置的 MCP 连接支持当前企业 endpoint；`tools:manage` 控制管理权限，个人专属令牌尚未实施。旧集成链接兼容跳转，Ollama/Cloud 设置、API/CLI/Chrome/Claw 集成和本地浏览器连接入口已删除。一次性令牌和绑定二维码只保留当前页面内存，身份切换时清空。


## 已迁移的部门管理

部门维护位于独立企业管理应用 `/admin/organization`。工作台设置已移除部门导航和旧组织读写页面；旧 `?section=org-structure` 及内部旧快捷调用显示迁移说明，由用户主动打开管理端。有无管理入口按当前企业的服务端 entries 展示，管理端仍复核 `org:manage`。开发地址使用当前主机 5174 端口，生产链接遵循静态部署 base。共享空间、加入企业、切换企业及个人设置仍由原流程处理。个人退出企业已由账户资料页承接，旧企业信息页已移除；旧成员页及其他管理依赖仍待收尾。


## 当前企业成员身份与退出

账户资料（`section=userprofile`）包含当前企业只读信息和本人退出操作，使用有效企业 ID，不误用账号默认企业。普通成员无需管理权限或成员名单读取即可确认退出；任何 owner 均须先转移所有权并调整角色，页面与现有后端规则一致。退出前显示企业名称和资源访问影响，失败保留错误和确认、提交中禁止重复操作，成功清除本地身份并在工作台登录页重新登录。企业/账号/角色变化使旧确认和迟到结果失效，企业资料变动通知会刷新只读信息。

旧企业信息页的治理编辑/删除已由独立管理端承接，工作台旧 `tenant` 设置书签与 `/platform/tenant` 路径进入账户资料页，个人资料与改密保持原流程。实现为 `CurrentEnterpriseMembership.vue`，沿用现有 GET `/tenants/current` 与 POST `/tenants/{id}/leave`，没有改变后端权限规则。
