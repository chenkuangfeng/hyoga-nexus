# Web 设计

Vue 3、TypeScript、TDesign、Pinia、vue-router（history 模式）、vue-i18n 与 Vite。`apps/web` 是 pnpm workspace，公共包与两个应用的边界见下文。下文页面、组件与业务状态路径相对 `workspace/src`，API、认证与语言路径相对 `core/src`。

员工工作台外壳为 `workspace/src/views/platform/index.vue`，左侧为 `workspace/src/components/menu.vue`，右侧为业务路由与共享的设置、上传任务、命令面板等组件。路由在 `workspace/src/router/index.ts`，登录入口为 `/login`，会话地址为 `/platform/chat/:chatid`。认证与当前企业由 `core/src/stores/auth.ts` 统一管理，布局偏好由工作台 `workspace/src/stores/ui.ts` 管理。平台管理路由已删除，未知地址使用公共 404 页面；独立企业管理应用部署于 `/admin/`。生产反向代理需分别为 `/`、`/admin/` 和 `/embed/` 配置静态回退，并将 `/api/`、`/wecom/` 转给 API。

模型设置（设置 → 模型管理，`views/settings/NexusModelSettings.vue` 与 `NexusModelEditorDialog.vue`）沿用 WeKnora `ModelSettings.vue`、`ModelEditorDialog.vue` 的布局与样式（类型标签页与计数、搜索、卡片网格、添加卡片、居中编辑抽屉、底部测试连接），数据来自 `api/nexus-models.ts`（`/tenants/{id}/model-settings`）。WeKnora 的一条模型对应 Nexus 的「供应商 + 模型档案」：`views/settings/nexusModelCards.ts`（纯函数，有单元测试）把供应商下的模型展开为卡片，并决定保存时复用已有供应商还是先建供应商（失败重试复用已建供应商）。服务商下拉列出调用者可管理的供应商与「自定义（OpenAI 兼容接口）」；编辑时修改 Key 会轮换整个供应商的 Key，界面提示受影响的模型数。默认模型在卡片菜单中按作用域设置（个人默认；空间共享模型且调用者为管理员时还可设空间默认），卡片显示默认标签。Key 只在提交时发送，提交后清空，不写入浏览器存储。省略 WeKnora 的内置模型、模型目录、调试抽屉、用量对话框、Ollama 与云服务来源。

智能体（`/platform/agents`，`views/agent/NexusAgentList.vue` 与 `NexusAgentEditorModal.vue`）沿用 WeKnora `AgentList.vue`、`AgentEditorModal.vue` 的卡片网格、编辑弹窗外壳（`SettingsModalShell`）与分区样式，只保留 Nexus 支持的四个分区：基本信息、提示词、模型配置（对话模型、温度、最大生成 Token、思考强度、最大迭代次数、模型调用超时）、工具配置（按分组的内置工具目录，显示可写、需审批、只读标记；空间未启用的工具对管理员提供「启用」，对成员不可选）。WeKnora 的这两个组件与其知识库、组织、渠道等 store 深度耦合，因此按其模板与样式重写为 Nexus 版本，原文件保留但不再被路由引用。表单与 `AgentDraftInput` 的映射位于 `views/agent/nexusAgentForm.ts`（纯函数，有单元测试）：温度与思考强度写入 `budgets.generation`，最大 Token、迭代与超时写入执行预算，工具写入 `kind=tool` 绑定，保存时保留其他预算键与非工具绑定（如技能）。「保存」= 保存草稿后立即发布新版本；发布失败时保留草稿并提示原因。删除为归档：列表不再显示，已有会话可读但不能继续对话。卡片菜单「开始对话」跳转 `/platform/creatChat?agent=<已发布版本 ID>`，对话页据此预选智能体。

采用现有主色、语义 token、系统字体与 TDesign 组件；按钮与标签提供可读名称，窄屏卡片与操作换行。

主对话页（`/platform/creatChat` 新建对话；`/platform/chat/:chatid` 会话与运行，路由入口 `views/chat/NexusChatRoutePage.vue`，对话核心 `views/chat/NexusChatPage.vue` 由 `sessionId` 属性驱动）按 WeKnora 复制：会话态的结构与样式取自 `views/chat/index.vue`（`chat-topbar`、`chat_thread`、`chat_scroll_box`、`msg_list`、悬浮的 `chat_composer`、`chat_overlays`），欢迎态取自 `views/creatChat/creatChat.vue`（标题、推荐问题区、输入框垂直居中）；窄容器（`compact`）使用 WeKnora 的嵌入布局。数据只来自平台 Run API，不调用 WeKnora 对话接口。旧的 `/platform/native` 地址重定向到上述页面。`/platform/knowledge-bases/:kbId/creatChat` 同样重定向到新建对话页（会话不挂载知识库）。

- `api/native-run-types.ts`：Run、事件、会话等类型与运行时校验，不依赖网络或 i18n，便于测试。
- `api/native-runs.ts`：类型化的请求封装；事件流使用 `@microsoft/fetch-event-source`，携带与 axios 相同的认证头，并从 `Last-Event-ID` 续读。
- `composables/useNativeRun.ts`：提交（每次提交生成幂等键）、跟随事件流、刷新 Run 视图、告警确认、取消、追加提示、回答等待输入。断线后从已持有的序号续读，不重新提交 Run。
- `views/native/nativeRunState.ts`（被对话页复用）：纯状态规则（按序号去重、助手文本按轮拼接、工具调用汇总、各状态下允许的操作）。服务端仍是状态的事实来源，页面不保存权限或终态。
- `views/native/NativeWatchdogBanner.vue`（被对话页复用）：运行监督告警条，仅在服务端返回 `attention_required` 且 Run 未结束时显示；三个操作（继续等待、发送提示、取消）都由父组件调用接口后刷新。

模型输出由 WeKnora 的 Markdown 管线渲染（`botmsg.vue` 与 `AgentStreamDisplay.vue`），输出经 DOMPurify 净化。

- 侧栏会话列表（`components/menu.vue`）只读取平台会话 `listSessions`，展示「我的会话」一个分组；IM、嵌入渠道与 API 文件夹尚未迁移，不生成对应分组。平台会话暂无改名、置顶、清空与删除接口，因此会话菜单不提供这些操作（`SessionSidebarRow` 在无菜单项时隐藏更多按钮）。
- 复用的 WeKnora 组件：`usermsg.vue`、`botmsg.vue`（含 `AgentStreamDisplay` 时间线与回答工具栏）、`MessageTimestamp`、`ChatQuestionMinimap`、`PendingPromptDock`、`ToolApprovalCard`、`AskUserCard`、`Input-field.vue`（`nexusMode`）。调用 WeKnora 接口的 `ChatHeader.vue` 按原模板复制为 `components/NexusChatHeader.vue`。
- 数据适配：`utils/nexusChatTranscript.ts` 把平台消息按 Run 分组为 WeKnora 行（一条用户消息 + 一条助手回答），历史回答的时间线由该 Run 的事件重建（打开会话时以最多 4 个并发读取 `GET .../runs/{id}/events`；读取失败时回退为正文）。`utils/nexusAgentEvents.ts` 把 Run 事件映射为 `agentEventStream`：文本、工具调用、`approval.*` → `tool_approval_required`、`input.*` → `agent_prompt_required`（ask_user）。审批参数只经 `GET .../approvals` 取得。
- 运行操作：`composables/nexusChatActions.ts` 由对话页提供；`ToolApprovalCard` 与 `AskUserCard` 检测到它时改调平台审批与回答接口（审批后 `useNativeRun.resume()` 继续跟随），否则保持 WeKnora 原行为。
- 占位：平台尚无后端的入口照常显示，点击统一提示「该功能暂未开放」——顶栏改名（含双击标题）、查看授权、删除会话、沙箱面板；欢迎页推荐问题与刷新；消息分叉、回滚、问助手、加入知识库、产物；输入框联网搜索、图片与附件上传、@ 引用、模型与思考强度。「复制为 Markdown」在前端实现。数据驱动的区域（追问建议、子智能体标签页、引用与附件抽屉、浏览器任务预览、后台任务）在没有数据时与 WeKnora 一样不出现。
- 智能体选择与 WeKnora 一致：输入框左侧的 `agent-mode-btn` 打开 `components/NexusAgentSelector.vue`（按 WeKnora `AgentSelector.vue` 的模板、定位与样式复制，只列平台已发布的智能体，归入「自定义智能体」；不读取 WeKnora 的 store 与接口）。会话已绑定智能体，会话内点击该按钮为占位。
- 已去掉 Nexus 自加的元素：运行状态标签、运行停滞告警条（`NativeWatchdogBanner.vue` 保留但不再挂载）、失败与排队提示行。运行失败时与 WeKnora 处理运行级错误相同：错误说明作为回答写入时间线，并弹出错误提示。因此对话页目前没有「继续等待 / 发送提示」与排队位置的入口；取消用输入框的停止按钮，追加指令用运行中的发送。
- 与 WeKnora 仍不同之处：欢迎页不显示宿主沙箱的项目目录条（WeKnora 仅桌面端显示）。
- 尚未完成（见 `openspec/changes/2026-11-04-weknora-chat-dialog/tasks.md`）：完整 `vue-tsc` 与 `pnpm build` 未在受内存限制的环境中验证；浏览器用例未执行。
- 智能体与模型设置页（`2026-11-05-weknora-agent-tool-model-settings`）：已通过 SFC 编译、LESS 编译与针对新文件的 `vue-tsc` 检查；完整 `pnpm build` 与浏览器验证需在内存充足的环境执行。

## pnpm workspace

`core`、`workspace`、`admin` 使用唯一锁文件与 `pnpm-workspace.yaml` 的 catalog。`tsconfig.base.json` 开启严格类型检查；两个 Vite 配置调用根 `createWebConfig` 工厂，统一 API 代理、PDF WASM 复制和依赖拆包。工作台保留主页面和 embed 两个入口，管理应用 base 为 `/admin/`。

原 `src` 和 `public` 分别移入 `workspace/src`、`workspace/public`；公共 API、认证、主题、编辑器及渠道组件抽到 `core/src`，公共包不引用应用。应用用 `@nexus-web/core/...` 访问公共源码，Vite 排除其依赖预构建并统一 Vue 实例。登录、改密保留原有组件与流程，管理应用登录后进入本应用首页。

`stores/entries.ts` 按当前企业查询应用入口；不存在的企业、缺失 entries 的旧缓存返回空入口。`scripts/check-boundaries.ts` 检查静态导入、导出和动态导入的方向。平台管理页面、专用模型目录适配器、桌面绑定与自动初始化入口已删除；旧集成页和本地浏览器连接入口已删除，IM 渠道迁入智能体页、MCP endpoint 迁入个人设置。管理端已接入权限外壳、企业/组织/成员/角色治理、策略、智能体与知识库管理、模型与 MCP、存储/检索、工具与技能、渠道、用量、运行状态及审计页面。智能体与知识库完整编辑器及 IM 面板由 core 复用。embed 服务端契约与 MCP 个人 endpoint 尚未完成；双应用完整构建/浏览器验收和工作台产物隔离仍待 E2.8。

认证恢复只使用已有令牌，不尝试桌面自动初始化。注册表单按是否持有邀请令牌分流：自助注册发送企业名称与编码，邀请注册只发送邀请与账号字段。两应用共用 404 页面，已删除的平台管理路由不再挂载应用页面；旧设置参数归一到 `general` 并移除旧 `panel` 参数。工作台改密路由先经过认证，临时密码账号先改密，避免初始化豁免绕过认证。

管理应用只承载本应用的路由；邀请与无企业身份的开户入口以原始 `fullPath` 转交员工应用，保留邀请参数。两个应用的未知路径使用共用 404 组件。

独立浮动助手及页面上下文桥已移除，普通聊天的工具结果卡片和资源刷新通知继续沿用原契约。`workspace/src/stores/pageDrafts.ts` 只管理 `open_page` 结果交给模型/MCP 编辑器的一次性草稿；不存储会话、面板布局或凭据，账号/企业切换时同步清空。同一身份的令牌刷新不丢弃待编辑草稿。智能体和自动化使用的写入授权级别契约保留，助手专用名称、布局、页面授权和个人设置已删除。

## 智能体渠道与 MCP 连接

`/platform/agents/:agentId/channels` 的 IM/embed 标签替代旧集成页；旧链接保留智能体 ID 并迁移到新地址，未指定智能体时进入列表。页面读取服务端的 `can_maintain` 与 `ownership`，只向维护者提供渠道操作。共享的 `core/src/components/IMChannelPanel.vue` 通过 `core/src/api/enterprise-connections.ts` 调用 Nexus 渠道接口：个人微信受企业外部渠道策略限制，企业自建应用从具有 `org:manage` 的配置列表中按智能体、用途和启用状态筛选；没有可选配置时提示联系管理员。企微机器人和 QQ 尚未核验，保持不可创建。二维码内容由 TDesign 在本地编码，不发送给第三方二维码服务；关闭、身份变化和卸载均终止轮询，过期响应不能回写。

账户设置的 `mcp-endpoints` 页面替代旧 MCP 服务集成页，提供只读连接地址和依据 `tools:manage` 授权的创建、编辑、停用、删除、令牌轮换及吊销。知识库用可读名称选择，提交稳定 ID；空知识库范围遵循后端“全部可读库”的含义。工具选项与服务端只读工具白名单保持一致。创建或轮换返回的令牌只保存在当前弹窗内存中，关闭、离开设置、身份变化或卸载时清空；元数据列表不接收令牌字段。所有异步响应和确认操作均校验当前作用域。

当前 MCP endpoint 仍是企业资源，并非个人专属令牌；个人令牌的持有与签发授权待 E2.4/E6 后续实施。embed 标签明确提示后端尚未接入，不创建虚假渠道。独立嵌入客户端保留，不能视作渠道后端已经完成。Ollama/Cloud 配置页、API/CLI/Chrome/Claw 集成页以及本地浏览器连接设置已移除；历史消息中的浏览器工具结果和任务展示继续保留。

## 企业管理端策略与权限

`admin/src/router.ts` 的受保护导航先使 `stores/context.ts` 失效，再刷新认证与权限；强制改密优先于业务。`AdminLayout.vue` 显示当前企业、成员企业选择器和按 API 权限提供的导航。没有 `entries.admin` 时显示无权限；权限请求失败时展示重试，不回退角色推断。上下文不持久化权限；账号、企业或管理入口变化立即递增请求代次并清空权限。

`/admin/policy` 的 `views/EnterprisePolicy.vue` 调用公共 `core/src/api/enterprise-admin.ts`：GET/PATCH `/tenants/{id}/admin/policy`，组织选项通过 `/org-units/tree` 读取。策略的枚举、布尔值与保留天数经过运行时校验。页面保留服务端快照，`policyChanges` 只提交不同字段；组织配置不可读时保留已有部门 ID，表单只显示配置数量，不暴露内部 ID 或允许手填。保存前说明渠道停用与内容清理后果，显式 null 关闭自动清理。每个请求、确认弹窗及保存结果校验代次，身份变化、权限重载或卸载使原操作失效。

界面参考 WeKnora `Settings.vue` 的设置导航、权限兜底与分组样式，以及 `TenantInfo.vue` 的加载、错误和提交反馈；采用 TDesign 表单与语义主题变量，按 Nexus 的企业策略契约重写，不调用 WeKnora 租户设置接口。首页不展示虚构统计，未迁移业务仅说明状态。开发时工作台链接、邀请与开户转交同主机 5173 端口；生产保持同源路径，查询参数原样保留。

## 管理端成员与邀请

`/admin/members` 由 `views/members/MembersPage.vue` 和 `useMemberAdministration.ts` 组成，复用已接通的管理外壳与权限上下文。界面参考 WeKnora `TenantMembers.vue` 的成员/待邀请标签、搜索与角色操作、邀请表单和链接流程，按 Nexus 现有 DTO 重写；不导入工作台组件，审计由独立 AuditPage 承接。成员列表展示 active/suspended，管理 API 以事务锁保护 owner 状态，停用和恢复确认后调用状态端点并刷新行；操作者修改自身状态后重校准认证与企业权限。剪贴板函数迁到 `core`，原工作台路径保留转导出。

公共 `api/enterprise-members.ts` 调用现有 `/tenants/{id}/members`、`members/by-email`、`invitations` 和 `invite-links`，无需本批修改后端契约。管理端成员列表一次返回全部 active/suspended 行，工作台候选接口仍只返回 active 行，搜索分页在客户端完成；响应的企业 ID 必须匹配路径，修改角色的用户 ID 也须匹配请求。人员邀请与链接采用联合类型，链接路径仅允许 `/join?token=...`，不接受外部地址、片段或额外参数。

控制器分别消费两个列表的成功/失败结果；身份、企业、权限代次或管理权限变化立即清表单、临时密码和链接。所有 mutation 的结果与确认回调校验代次，关闭/卸载后旧确认不能发请求；表单秘密在提交时先清除。角色修改/移除要求成员行来自当前列表，前端提供 owner 规则与最后所有者保护，服务端仍在事务中授权。自身变更会刷新 `/auth/me` 与当前企业权限，即使默认企业发生变化也不复用旧权限。

邮箱流程只在选择创建新账号时提交用户名和临时密码；返回值明确区分 invited 与 created。邀请链接的有效期按 1–30 天校验；撤销只影响未完成的邀请/后续链接使用。加入申请已在管理端接通。停用只在 active 与 suspended 间转换，DELETE 仍写入 revoked；企微目录同步不能重激活人工停用成员，离职/移出范围仍撤销成员。工作台旧成员治理页已删除，E2.8 仍需确认工作台产物隔离。

管理端 API 地址与静态页面路径分开：公共 `getApiBaseUrl` 去掉页面 base 末尾的 `/admin`，`/admin/` 请求 `/api/v1/...`，`/nexus/admin/` 请求 `/nexus/api/v1/...`；员工端与其他子路径部署继续保留自身前缀。这样管理页面不会请求不存在的 `/admin/api/v1/...`。

## 管理端加入申请审批

成员页第三个标签按需挂载 `JoinRequestsPanel.vue`，承接原工作台审批面板的待处理列表、部门/角色必选和拒绝原因流程，界面继续使用 WeKnora 成员页的表格、反馈与 TDesign 表单模式。列表调用 `/tenants/{id}/join-requests`，批准与拒绝分别 POST `/{application_id}/approve` 和 `/reject`；公共成员客户端校验待处理状态、基础角色与批准回执的用户、角色、active 状态。没有新增后端契约或扩大权限。

申请和部门并行读取，独立消费失败。部门接口需要 `org:manage`，批准接口仍由后端按 `members:manage` 检查；前端只允许从可读列表选启用节点，不能手工绕过。组织路径构建有循环保护。成员权限缺失时不读取申请，组织权限缺失/失败只禁止批准，不阻断拒绝。申请列表失败时不显示成功空态。

组件用代次隔离账号、企业、权限和刷新请求。取消表单清空目标与输入，卸载清空列表；已发出的审批晚到时不得删除新作用域的行或发出成员刷新事件。审批过程中锁定重复提交与关闭，向父页同步忙碌状态；成功批准才通知父页重新读取成员。拒绝确认中说明 7 天冷却，失败保留输入。只显示待处理记录，不用本地缓存生成审批历史。


## 管理端部门组织

`/admin/organization` 由 `OrganizationPage.vue` 和 `useOrganizationAdministration.ts` 组合，承接原工作台部门页的节点与成员归属流程，以及 WeKnora 组织设置的表格、反馈和确认模式。公共 `enterprise-organizations.ts` 调用当前企业 `/org-units` 的树、节点和成员归属接口，运行时校验单根、唯一节点、完整父引用、无环连通结构及回执企业/节点/成员。树遍历与子树排除采用迭代算法，避免深层组织递归溢出。

完整树与可选企业成员并行加载且分别反馈失败；所选节点的直接成员另用请求序号，阻止迟到响应覆盖新选择。企业、账号和权限代次变化同步清空状态；确认还绑定节点选择及成员请求序号。写入后重读树、候选和节点成员，首次分配自动设为主部门等规则由服务端结果决定。移动只提交变化字段，保留未变的停用父节点；根不提供父节点选择。删除既检查已读直接成员，也保留服务端历史关联冲突反馈。

`org:manage` 控制页面与节点操作，`members:manage` 仅额外用于全企业候选列表。按现有接口 `source=wecom` 阻止界面中的节点及归属写入，手工子部门可建在启用的企微父节点下。通用后端接口尚未执行来源只读校验，树 DTO 未暴露手工根的 `external_id`，成员归属无同步来源字段，因而混合根上的同步归属不可完整辨识；来源保护、可辨识契约及同步配置/状态仍待后续实施。


## 企业管理主框架与内容样式

企业管理主框架以当前 workspace 的 `menu.vue` 与 `UserMenu.vue` 为视觉基线，在 `admin/src/AdminLayout.vue` 实现独立外壳：260px 可折叠侧栏（折叠 48px）、顶部品牌和折叠按钮、图标导航、固定左下角用户入口。账户弹层提供当前成员身份的企业切换及退出，不提供关闭或返回工作台入口。折叠偏好使用独立本地键，窄窗口展开为 220px；导航区独立滚动，主内容独立滚动。折叠控件与账户入口支持键盘及可读标签，弹层支持 Escape、外部点击关闭与焦点恢复。

工作台菜单包含会话、邀请和资源逻辑，管理端不引入这些依赖，也不互相导入应用组件。认证、企业权限、主题 CSS、TDesign 覆盖、`settings-section.less` 与 `settings-table.less` 由 core 复用；`SettingsModalShell` 继续服务工作台设置与编辑器，管理端业务内容保留公共设置行与表格风格。

概览与策略沿用常规设置行：左侧标签/说明、右侧控件，设置组采用分隔线。成员列表沿用设置页标题、紧凑工具按钮、搜索框及带边框表格；部门页沿用原组织页的双栏尺寸、面板、节点和操作间距。标题使用统一字号令牌，普通内容内边距 40px/48px，成员列表 20px/28px；窄屏内容缩小内边距，设置控件可换行。此次调整不改变 API、权限、表单提交及确认逻辑。


## 企业信息

管理端 `/admin/enterprise` 由 `EnterpriseInfo.vue` 编排，公共 `enterprise-info.ts` 校验现有 GET/PATCH `/tenants/current` 的完整详情和目标企业 ID，删除沿用 DELETE `/tenants/{id}`。页面使用公共设置行，owner 可编辑和归档；只有名称/描述变化时才提交，删除确认绑定当前快照名称。权限与作用域代次驱动请求失效，失败保留可重试状态。删除成功清除本地身份，在管理应用内重新登录。企业编码接口和工作台旧管理页隔离仍待后续。


## 角色与权限

`admin/src/views/roles/RolesPage.vue` 组合列表、权限选择和成员分配，`useRoleAdministration.ts` 负责服务端目录、操作者授权、表单确认和身份隔离。`core/src/api/enterprise-roles.ts` 消费现有角色与权限接口，运行时校验权限数组、内置标记及角色企业 ID；不改变后端契约。

核心目录/角色/操作者授权全部成功后开放编辑，成员和分配列表独立读取且需成员管理权限。选择范围受当前操作者授权约束，内置角色只读，所有写入确认后执行。写入成功后刷新身份与当前企业权限，区分原写入失败和后续刷新失败；身份代次保证旧操作不能在企业切换后继续刷新和展示成功。部门批量分配按下述流程实现，角色到企业智能体的使用授权按下述流程实现，完整资源管理仍待后续。


部门批量分配复用角色页确认与身份校准，在组织树成功读取后用 `organizationRows` 生成完整路径选项；停用节点不可选。角色目录、成员分配区和部门树分别反馈失败。客户端只提交部门路径对应的稳定 ID 与 `role_id`，对 assigned/skipped 字符串数组及互斥去重做响应校验，结果使用全局反馈跨权限刷新导致的页面卸载展示。服务端在企业锁与同一事务内，先校验成员管理、角色管理和可授予范围，再批量写入；校验助手由单成员与批量接口共用。


角色到企业智能体授权由 `AgentRoleGrantsPanel.vue` 独立编排候选/既有授权加载和确认，复用角色页的身份校准回调。仅列出现有列表可见的 enterprise 资源，按真实名称选择角色与智能体；未解析的授权单独提示。选择目标后回填 view/run，整体替换与空数组撤销由既有 PUT 执行，服务端保留每项授予权限及知识库范围校验。独立加载失败、保存失败保留草稿、选择代次与作用域代次共同阻止过期确认及响应。


## 工作台旧部门设置收尾

工作台设置导航不再注册部门管理，旧 `OrgStructure.vue` 已删除，其组织读写不会再随设置页面打包。旧 `section=org-structure` 保留 `AdminSectionMoved.vue` 迁移说明，依据当前企业服务端 entries 提供显式管理应用链接；开发使用同主机 5174，生产按应用 base 构造 admin/organization。不会自动跨应用导航，管理端继续校准身份和组织权限。旧书签被识别为迁移区，不受原部门能力/owner 导航门槛影响，也不会因当前导航没有此项而自动丢回通用设置。

旧企业信息页现已由账户成员身份区和独立管理端承接后移除；旧成员治理页也已移除，其他管理配置与产物隔离仍待后续验收，共享空间、加入企业或企业切换保持原流程。


## 管理端审计日志

`AuditPage.vue` 与 `useAuditAdministration.ts` 消费现有最近记录接口和 UTC 日期导出，不增加后端契约。列表最多读取 500 条，本地筛选明确只覆盖已加载范围；元数据通过 Vue 文本渲染，未知动作/结果保持原始值。`enterprise-audit.ts` 校验响应结构、自然日有效性与日期差，导出要求 NDJSON Blob，通过认证请求层获取后下载并释放对象 URL。身份/权限代次、列表请求序号和导出请求序号分别阻止过期列表、详情和文件交付。


## 个人退出企业与旧企业信息页移除

`UserProfile.vue` 组合 `CurrentEnterpriseMembership.vue`，后者独立读取有效企业详情，显示真实只读信息与本人角色。退出直接使用现有成员接口，无需先获取全员名单；所有 owner 均禁止直接退出。确认绑定当前企业/账号/角色代次，提交中禁止关闭及重复提交，失败保留状态，成功清除本地身份并在本工作台登录页重新登录。企业变动通知可刷新只读信息，提交期间不因后台通知重置操作锁。旧 `TenantInfo.vue` 和导航被删除，tenant 设置书签及旧路由统一进入 userprofile；治理编辑/删除由 admin 页面承接，不改变服务端行为。


## 工作台旧成员治理页清理

工作台不再注册 members 设置导航，删除旧 `TenantMembers.vue` 和只被其引用的 `JoinApplicationsPanel.vue`。旧 members/部门书签共用参数化 `AdminSectionMoved.vue`，按内部目标枚举构造独立管理应用地址；成员迁移说明提供 members/audit 链接，无入口时说明权限不足，不请求治理接口。成员功能已由管理端成员页、审批面板和审计页承接，前后端真实权限保持不变；共享空间及个人加入/邀请流程保留。

### 企业智能体编辑器复用

完整 Nexus 编辑器、技能面板及表单纯函数位于 `core/src/components/agent-editor/`；头像、模型选项和推理档位辅助同属 core。工作台原辅助函数路径只做兼容转导，避免重复实现。页面各自拥有导航与目录，core 不导入应用；编辑器通过 `open-model-settings` 事件交回导航。`creationScope` 缺省为个人，企业创建走原管理接口。企业 DTO 和知识库候选在 `core/src/api/enterprise-agents.ts` 运行时校验。

编辑器使用请求代次隔离可见性、目标、企业及卸载，保存固定请求企业，写草稿后再次核对代次才发布。发布失败保留 draft ID；目录刷新不卸载编辑器。后台目录仅展示原 API 的可见企业记录，归档与角色使用授权沿用服务端契约。完整管理资源目录、独立恢复、部门/成员分配和真实 API 端到端验收尚未完成。

### 企业知识库目录、编辑与管理员指定

`admin/views/knowledge` 以组合函数管理原生目录、目标及内容管理员，`core/api/enterprise-knowledge.ts` 校验现有原生知识库与管理员 DTO。只显示所属企业的 enterprise 记录，拒绝不一致的共享标记与重复记录；不通过旧适配器推断归属或管理权限。成员列表独立加载且受 `members:manage` 限制，列表失败不影响已成功加载的管理员撤销。新增使用完整服务端响应，撤销后重读，区别写入失败与写入成功后刷新失败。`KnowledgeContentPage.vue` 按库类型组合文档、FAQ、Wiki 管理，`core/api/enterprise-knowledge-content.ts` 对相同后端契约做运行时响应校验；企业、用户、目标、管理权限和卸载代次阻止迟到结果污染页面，Wiki 编辑提交版本号以展示并发冲突。知识库卡片通过同一客户端调用显式企业路径 DELETE，权限及代次守卫保护确认和回执，成功后重新读取目录。完整设置编辑器中的共享面板沿用组织共享 API，新增和改级别由服务端校验 tenant 可见范围及 `external_sharing`，撤销现有共享仍可执行。当前尚未迁移批量导入导出、标签/目录、分块预览、Wiki 修订历史；共享空间端完整业务验收仍待 E2.8。

身份代次、查询代次与目标代次阻止旧确认和迟到结果污染当前企业；提交中锁定重复写入与目标切换，身份变化仍立即清理状态。完整知识库编辑器及其真实依赖位于 `core/src/components/knowledge-editor/`，通过宿主注入导航、作用域代理隔离异步请求。工作台保留个人创建与设置导航；管理端使用现有企业创建/更新接口，保存时合并原生 settings 快照和未知配置并单次 PATCH，存储/向量绑定只读。创建后读取失败可重试同一 ID。目录受众面板通过现有接口维护成员及部门范围，分别按 `members:manage`、`org:manage` 读取候选；不可读类别原样保留，智能体绑定冲突由服务端拒绝。管理员操作继续按资源权限控制。卡片/面板沿用后台设计，选择目标后将焦点移到管理员区，窄屏表格仅内部滚动。内容页面复用文档/FAQ/Wiki 原生接口，按类型显示 CRUD、上传下载和重新索引能力；版本冲突提示要求重载后重编辑，系统 Wiki 页面只读。管理外壳进入 600px 以下自动收起侧栏，保留手动展开和独立桌面偏好。知识库删除/共享治理仍未完成。


管理端 `/models` 使用 `core/src/api/enterprise-models.ts` 校验企业路径下的模型设置 DTO，并过滤个人 Provider。页面按 `models:manage` 控制访问；服务端继续负责不可变版本、默认值类型匹配、密钥加密与停用治理。身份/企业/权限变化会作废旧请求。


管理端 `/mcp-endpoints` 复用 `core/api/enterprise-connections.ts` 的企业路径 API 和严格 DTO 解析，使用 `tools:manage` 权限上下文；令牌明文仅保存在页面临时状态，身份、企业或权限代次变化会作废请求并清空秘密。知识库选项以名称呈现，提交稳定 ID；端点执行期的白名单与访问范围仍由 MCP 服务端复核。

MCP 客户端服务目录的交互实现位于 `core/components/mcp-admin/`，工作台工具箱通过兼容薄宿主接入，管理应用用独立 `/mcp-services` 页面组合；管理员权限由宿主服务端上下文注入，非管理成员的工作台保留只读目录。新工具发现后关闭启用状态；每个工具可设置风险和调用审批，降低风险前由界面确认、服务端保留观察风险并计算最终级别。存储配置与工作台产物隔离仍待后续。

## 企微组织来源与状态刷新

组织树与节点 DTO 使用 `sync_managed` 表达结构只读，包含映射外部部门的手工根。成员归属 DTO 使用 manual/wecom/mixed，界面允许设置主部门与撤销手工贡献，pure wecom 删除由前后端共同拒绝；混合来源撤销前提示保留企微贡献。WecomPage 在 requested 状态每 5 秒读取一次现有配置，最多 12 次；完成/失败停止，轮询不重置凭据草稿，代次保护账号、企业、权限、卸载与正在保存的配置。

## 企业编码只读展示

企业详情客户端严格校验 code 为 string/null。管理端 EnterpriseInfo 页面使用既有 SettingsRow、主题与剪贴板工具显示只读编码和复制反馈；空值禁用复制。复制请求与账号/企业/权限、页面代次绑定，切换或卸载后的结果不能污染当前页面。

## 工作台旧模型孤立实现清理

设置只挂载 Nexus 模型页，旧 WeKnora ModelSettings、ModelEditorDialog、ModelDebugDrawer 及独占的 modelProviders/modelProvidersState、modelEditorSourceState、modelCopyName、weknoraCloudModels、browserPairingOrigin 已删除。共享文案、解析器 Cloud 状态及通用 API 不按名称批量移除，依赖包仍被其他页面使用。

聊天工具继续通过 pageDrafts 交付无凭据模型草稿。Nexus 页面等待当前目录加载后一次消费，显式映射 vllm→vision、asr→speech；local 来源提示不支持。模型深链接按实际 profile id 定位且校验 canManage。账号/企业/基础角色变化清空旧页面和表单；对话框以 scope key 重建，关闭/卸载或目标变化使旧测试、供应商→模型写链失效，凭据不保留在重试状态。仅 provider id 用于模型失败后的复用。

## 企业存储与向量库入口隔离

工作台不再导入 StorageBackendSettings/VectorStoreSettings。固定 MIGRATED_ADMIN_SECTIONS 注册表为旧部门、成员、存储与向量库书签提供标题、说明和 Admin 目标；hasOwnProperty 检查防止继承属性成为目标。Settings 保留旧 section 值，并对迁移说明绕过原写页面的角色与能力门槛，说明本身只消费身份 entries，不请求或写入配置。AdminSectionMoved 链接随当前身份变化，不自动跳转，成员旧书签仍提供独立审计入口。

core 的 KBStorageSettings/KBVectorStoreSettings 继续通过真实目录适配器读取可用配置，现有绑定与快捷调用保留。共享适配器和文案不是旧页面的独占资源，不随治理页删除。
