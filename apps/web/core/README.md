# @nexus-web/core

两个 Web 应用共用的源码包，不单独构建或部署。

- `src/api/`：类型化接口与请求契约；`enterprise-admin.ts` 提供企业策略、部门选项校验与差异补丁；`enterprise-members.ts` 校验成员、人员/链接邀请及加入申请审批的真实契约；`enterprise-organizations.ts` 校验单根无环组织树、节点与成员归属回执，并提供当前企业内的节点和归属操作；`enterprise-knowledge.ts` 校验企业知识库目录、内容管理员、部门/成员读取受众和按企业作用域删除；`enterprise-knowledge-content.ts` 校验企业文档、FAQ 条目和 Wiki 页面内容接口；`enterprise-models.ts` 校验企业共享 Provider、模型版本、默认值及连接测试契约；`enterprise-storage.ts` 校验企业存储目录及已实现的本地存储增删、测试接口；`enterprise-vector-stores.ts` 校验企业向量库能力、动态字段和注册/更新/连接测试契约；`enterprise-graph-stores.ts` 校验企业图存储目录、能力状态、Neo4j 登记及测试契约；`enterprise-wecom.ts` 校验企业微信绑定状态、自建应用目录和通讯录同步请求；`enterprise-skill-submissions.ts` 校验企业技能投稿审核条目、纯文本详情和审核回执；`nexus-agents.ts` 校验智能体工具目录基础结构并封装企业级内置工具启停；`enterprise-usage.ts` 校验企业 Token 报表和月度限额 DTO；`native-runs.ts` 提供 Native 会话、Run 事件与中断阻塞状态的校验及操作；`enterprise-connections.ts` 提供企业智能体渠道审核、渠道生命周期、企业 MCP 只读端点及其作用域客户端。
- `src/stores/`：认证、企业身份、资源缓存与刷新排序；应用入口来自服务端成员身份的 `entries`。
- `src/composables/`、`src/utils/`：主题、字体、请求与令牌刷新等基础逻辑；剪贴板统一提供现代 API 和 HTTP 环境降级；离线图标初始化阻止外网 CDN 请求，配合两应用本地 SVG sprite。
- `src/components/SettingsModalShell.vue`、`SettingsRow.vue`：设置页与管理端共用的导航外壳和标准设置行。
- `src/components/knowledge-editor/`：工作台和管理后台共用的完整知识库编辑器与设置组件；宿主负责导航，知识库管理端受众控制由 `api/enterprise-knowledge.ts` 提供类型化契约。
- `src/components/mcp-admin/`：工作台工具箱与管理后台共用的 MCP 服务编辑器、工具发现/启停面板和配置纯函数；外层应用注入企业身份及管理权限。
- `src/styles/`：原设置页主题、TDesign 全局覆盖，以及设置标题/行/表格 mixin；工作台原 CSS 路径转导入这些公共实现。
- `src/i18n/`：公共语言资源与审计、扫描工具。
- `src/views/auth/`：公共登录与改密组件；自助注册只创建企业，邀请注册加入已有企业。
- 登录页支持按企业编码发起服务端企业微信扫码登录；企业/目录状态错误以登录页提示呈现。扫码凭据和 OAuth state 由服务端处理，浏览器不接触应用 Secret。
- `src/components/IMChannelPanel.vue`：智能体 IM 渠道面板，遵循维护权限、归属与企业策略，二维码在本地生成；接口封装在 `api/enterprise-connections.ts`。
- `src/components/NotFound.vue`：两个应用共用的未知页面提示。

应用经 `@nexus-web/core/...` 导入源码。Vue、TDesign、Pinia、vue-router 与 vue-i18n 使用 peerDependencies，共用 catalog 版本。公共包不得反向导入两个应用，`pnpm test` 检查该边界。

在 `apps/web/` 运行 `pnpm --filter @nexus-web/core type-check` 或 `pnpm --filter @nexus-web/core test`。编辑器、公共组件和样式的后续抽取见企业化提案 E2.3。

## 智能体使用受众

`src/api/enterprise-agent-audience.ts` 校验智能体部门/成员受众并封装整体替换接口；`src/components/agent-editor/AgentAudienceDialog.vue` 在管理端智能体目录和工作台共享设置中复用。受众直接授予 view/run，不覆盖角色授权；候选按成员和组织目录权限分别读取，无权或失败时保留对应已有项，避免空列表覆盖。
