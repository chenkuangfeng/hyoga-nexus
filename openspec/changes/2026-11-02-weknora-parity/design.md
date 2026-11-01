# WeKnora 功能清单与映射

来源：`Tencent/WeKnora`（MIT 许可，提交 `80e8345`）的 `frontend/src/router/index.ts`、`components/menu.vue`、`stores/menu.ts`、`views/**`、`components/**`。本文件只记录功能与对应关系，实施时按 AGENTS.md 的要求阅读各模块源码后再编写。

图例：✓ 已有（本仓库已实现，可能界面不同）；◐ 部分已有；✗ 未有；— 建议排除。
"路线图"列指 `docs/roadmap.md` 中已经规划的步骤。

## 1. 外壳与导航

| WeKnora 功能 | 源码 | 本仓库 | 路线图 |
| --- | --- | --- | --- |
| 侧栏：Logo、搜索（命令面板 ⌘K）、折叠/展开、拖拽调宽 | `components/menu.vue`、`PanelResizeHandle.vue`、`GlobalCommandPalette` | ◐ 侧栏已有，无搜索面板，不可拖拽调宽 | — |
| 空间切换（TenantSelector） | `components/menu.vue` | ✓ 侧栏空间选择器 | — |
| 新建对话入口，下挂最近会话（置顶、重命名、清空、批量管理） | `menu.vue`、`stores/menu.ts` | ✗ 会话列表无置顶、重命名、清空、批量 | — |
| 顶级菜单：新建对话、知识库、制品库、智能体、自动化、工具箱、组织、设置 | `stores/menu.ts` | ◐ 我方分组为工作台/空间/个人/平台管理 | 见第 4 节 |
| 助手入口（AssistantButton） | `components/assistant/` | ✗ | — |
| 用户菜单、退出、语言切换 | `menu.vue` | ◐ 退出已有；无语言切换 | — |

## 2. 认证与入门

| WeKnora 功能 | 源码 | 本仓库 | 路线图 |
| --- | --- | --- | --- |
| 登录（账号密码、OIDC、企业微信扫码） | `views/auth/Login.vue` | ✓ 账号密码与企业微信；✗ OIDC | 2 |
| 邀请注册（`/register?token=`） | `Login.vue` | ✗ | 2 |
| 工作空间引导（`/onboarding/workspace`） | `views/auth/WorkspaceOnboarding.vue` | ✗ | 2 |
| 加入组织（`/join?code=`） | `router/index.ts` | ◐ 组织成员由管理员分配，无邀请码 | — |
| 账号页（改密、绑定企业微信） | `settings/UserProfile.vue` | ✓ 我的账号 | — |

## 3. 对话

| WeKnora 功能 | 源码 | 本仓库 | 路线图 |
| --- | --- | --- | --- |
| 对话页与消息流、停止、重新连接 | `views/chat/index.vue` | ✓ 对话工作台 | — |
| 深度思考（deepThink） | `chat/components/deepThink.vue` | ✗ | 3 |
| 工具结果渲染：检索结果、分块详情、文档信息、网页搜索/抓取、Shell、沙箱文件、图查询、Wiki 编辑、数据库查询、MCP 结果、计划、Grep、OpenPage 等 | `chat/components/tool-results/*`（约 25 个） | ✗（仅显示工具状态） | 6、7、8 |
| 工具审批卡（ToolApprovalCard）、宿主审批（HostApprovalCard） | `chat/components/` | ◐ 运行中的审批事件已有，无卡片 UI | 3 |
| 追问卡（AskUserCard）、待处理提示（PendingPromptDock） | `chat/components/` | ◐ 输入请求已有 | 3 |
| MCP OAuth 卡 | `McpOAuthCard.vue` | ✗ | 7 |
| 子智能体流（ChildAgentStream、TabBar） | `chat/components/` | ✗ | 3 |
| 协作任务（CollaborationTasks）、后台任务（BackgroundWork） | `chat/components/` | ✗ | 3 |
| 进度更新（ProgressUpdates）、RAG 流水线进度 | `chat/components/` | ✗ | 6 |
| 制品面板与抽屉（ChatArtifactsPanel/Drawer） | `chat/components/` | ✗ | 新增 |
| 沙箱桌面、沙箱终端、浏览器任务预览 | `SandboxDesktop.vue`、`SandboxTerminal.vue`、`BrowserTaskPreview.vue` | ✗ | 8 |
| 记忆步骤（ChatMemoryStep） | `chat/components/ChatMemoryStep.vue` | ◐ 记忆快照与审核已有 | 本仓库阶段一至三 |
| 模型分支、会话快照 | — | ✓ 模型分支、记忆快照 | — |
| 嵌入式对话（embed） | `views/embed/*`（5 个） | ✗ | — |

## 4. 知识库

| WeKnora 功能 | 源码 | 本仓库 | 路线图 |
| --- | --- | --- | --- |
| 知识库列表与编辑（类型、图标） | `knowledge/KnowledgeBaseList.vue`、`KnowledgeBaseEditorModal.vue` | ✗ | 6.1 |
| 文档列表、卡片视图、文件夹树、标签、批量操作 | `knowledge/components/*` | ✗ | 6.1 |
| 上传：文件、URL、手工录入、FAQ，上传确认 | `KbUploadSourceDropdown.vue`、`UploadConfirmDialog.vue` | ✗ | 6.1 |
| 数据源与同步日志 | `settings/DataSourceSettings.vue`、`DataSourceSyncLogs.vue` | ✗ | 6.1 |
| 分块、解析器、向量存储、存储、模型配置（每库） | `settings/KBChunkingSettings.vue` 等 | ✗ | 6.1 |
| 分块调试 | `settings/KBChunkingDebug.vue` | ✗ | 6.3 |
| 图像库与图像流水线 | `knowledge/gallery/*`、`ImagePipelineSettings.vue` | ✗ | 新增 |
| Wiki 浏览、修订、文件夹操作 | `knowledge/wiki/*` | ✗ | 新增 |
| 图谱设置（可选） | `settings/GraphSettings.vue` | ✗ | 6.4 |
| FAQ 条目管理 | `components/FAQEntryManager.vue` | ✗ | 6.1 |
| 共享设置 | `settings/KBShareSettings.vue` | ◐ 空间与组织绑定 | — |
| 活动记录 | `settings/KnowledgeBaseActivitySettings.vue` | ✗ | 6.1 |

## 5. 智能体、制品、自动化、工具箱

| WeKnora 功能 | 源码 | 本仓库 | 路线图 |
| --- | --- | --- | --- |
| 智能体列表与编辑（模型、工具、技能、知识库、提示词） | `agent/AgentList.vue`、`AgentEditorModal.vue` | ◐ 智能体创建与发布（Native）；无编辑器的完整配置 | 3 |
| 制品库 | `artifacts/ArtifactLibrary.vue` | ✗ | 新增 |
| 自动化列表、详情、编辑器、状态 | `automation/*`（4 个） | ✗ | 新增 |
| 工具箱（分段） | `toolbox/Toolbox.vue` | ✗ | 7 |

## 6. 组织

| WeKnora 功能 | 源码 | 本仓库 | 路线图 |
| --- | --- | --- | --- |
| 组织列表与设置（成员、共享） | `organization/OrganizationList.vue`、`OrganizationSettingsModal.vue` | ✓ 组织树、人员归属、空间绑定、组织访问（本仓库设计更细，见 `2026-11-01-user-org-management`） | — |

## 7. 设置（WeKnora 共 22 个分区）

| 分区 | 本仓库 | 说明 |
| --- | --- | --- |
| general 通用 | ✗ | 需要确定哪些设置保留 |
| ollama | — | 排除（本地模型服务，我方模型配置已有供应商模式） |
| weknoracloud | — | 排除（该产品的云服务） |
| models 模型管理 | ✓ 模型设置（供应商、模型、默认） | 界面需按 WeKnora 重做 |
| websearch 网页搜索 | ✗ | 7 |
| chathistory 对话历史 | ✗ | — |
| defaults 默认设置 | ◐ 默认模型 | — |
| memory 记忆工作区 | ✓ 记忆（本仓库阶段一至三，更完整） | — |
| vectorstore 向量存储 | ✗ | 6.1 |
| parser 解析引擎 | ✗ | 6.1 |
| storage 存储引擎 | ✗ | 6.1 |
| sandbox 沙箱 | ✗ | 8 |
| system 版本信息 | ✗ | — |
| system-global 系统设置 | ✗ | 管理员 |
| model-catalog 模型目录 | ✗ | 管理员 |
| runtime-queues 任务队列 | ✗ | 管理员（本仓库有队列，无界面） |
| platform-api-keys 平台 API 密钥 | ✗ | 管理员 |
| system-audit-log 审计日志 | ✗ | 管理员（本仓库有审计记录，无界面） |
| userprofile 个人资料 | ✓ 我的账号 | — |
| mymemory 我的记忆 | ✓ 记忆 | — |
| assistant 助手设置 | ✗ | — |
| envvars 环境变量 | ✗ | — |
| tenant 空间信息 | ✓ 空间组织/角色 | — |
| members 成员 | ✓ 角色与权限（成员与角色） | — |
| mcp / skills / browser 连接 | ✗ | 7、8 |

## 8. 系统管理（WeKnora 的 system/*）

| 功能 | 本仓库 | 路线图 |
| --- | --- | --- |
| 用户管理（创建、重置密码） | ◐ 角色页可创建账号 | — |
| 模型目录、系统设置 | ✗ | — |
| 运行队列 | ✗ 界面 | 3 |
| 审计日志 | ✗ 界面（后端有） | — |
| 平台 API 密钥 | ✗ | 新增 |

## 9. 集成

| 功能 | 本仓库 | 建议 |
| --- | --- | --- |
| MCP 服务器集成（页面） | ✗ | 7 |
| API 集成 | ◐ 后端有接口 | 新增页面 |
| CLI 集成、Chrome 扩展、Claw 技能落地页 | — | 排除（产品形态不同） |
| IM 渠道 | ✗ | 9 |

## 10. 本仓库已有、WeKnora 没有的能力（扩展基础）

- 记忆：草稿审核、来源消息 ID、记忆预算、会话快照、自动捕获（阶段一至三）。
- 组织：组织树、人员归属、空间绑定、组织访问与来源标记、组织成员的角色（不自动成为成员）。
- 运行：Run 状态机、租约、运行事件、审批与输入请求、会话队列与忙碌排队。
- 模型：所有者密钥与空间共享密钥的分离、按次授权。

这些能力应在 WeKnora 的界面上继续扩展，而不是替换。
