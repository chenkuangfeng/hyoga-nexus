# 设计：当前会话整理为技能

## Worker workspace 与 local 技能脚本（扩展范围）

- 数据库保持技能内容的事实源，避免多 Worker 因各自磁盘不同步看到不同版本。每次 Run 在权限检查之后读取完整不可变版本，用内容哈希目录名投射到该 Worker 的 `skills/` 缓存；每个工具调用仍检查当前绑定、所有者、版本状态和授权。技能脚本目录不可写。
- 持久布局按租户及用户稳定 ID 分区：`<workspace-root>/<tenant-id>/users/<user-id>/{skills,data}`，并创建 `data/tmp`。私有技能工作副本位于用户 `skills/` 下；平台技能使用独立只读根；用户名和智能体名不作为授权路径键。用户的 `data/` 跨该用户技能共享，不属于某个 Agent。
- 目标是 `skill_manage` 读写用户 workspace 的草稿副本；`skill_save` 在用户确认后从该副本创建有界快照，校验路径不含链接/特殊文件、大小和文件数量上限、草稿基线哈希，之后复用现有扫描与数据库版本发布逻辑。发布成功后缓存按新哈希建立，不原地覆盖旧版本。当前实现仍由既有数据库事务读写草稿，再将结果镜像到 workspace；workspace 优先编辑及保存时同步回数据库尚未完成，见 `tasks.md` 4.3。
- 多 Worker 的 `data/` 使用部署指定共享持久卷，并以用户级跨进程锁串行化写入；技能内容缓存仍是每 Worker 本机缓存，不要求共享技能磁盘。该卷需备份、容量与权限管理。当前只允许 workspace 位于受信任的本地/共享文件系统；不把普通对象存储伪装成 POSIX 工作区。
- 生产 local 调用不执行无约束的 `LocalExecutor`。沿用本仓库已实现并验收的 bubblewrap jail 来承载 local 技能子进程：系统根只读、只绑定当前用户数据和当前 Run 的只读技能/依赖，outputs 可写，tmp 指向 `data/tmp`，网络按档位策略配置，进程使用非 root 身份及资源/超时限制。执行前检查 Linux、bwrap 可用性与隔离验收指纹；任何一项不满足都 fail closed。Docker 与托管后端仍可用。
- 学习操作会在当前会话完整上下文上运行。输入预算使用每三个 UTF-8 字节约一个 token 的保守近似，并计入消息/工具调用开销；这比把中文 UTF-8 的每个字节直接当成一个 token 更贴近模型 usage，实际 usage 返回后仍以供应商数据累计。
- 若模型输入连同输出预留超过本 Run 剩余 token 预算，在发送模型请求前将本轮模型视图中的较早对话轮次替换为标明“不完整、非指令”的历史摘录；保留系统指令、当前用户请求与最近完整工具交换。该预算压缩只影响当次请求，不修改 `messages` 表原文；若当前请求/最近交换本身仍放不下，则明确按预算耗尽处理。
- file tool 的虚拟 `/workspace` 与用户持久数据入口分开授权：用户工作区工具映射仅能访问该用户根；Run 结束继续清理会话临时区，保留 `data/`。同一用户的并发 Run 通过 workspace 锁协调修改；平台需避免把用户私有 data 自动登记为可分享 artifact。

### 威胁边界与取舍

Hermes 的 `HERMES_WRITE_SAFE_ROOT` 仅限制专用文件写工具，官方安全文档仍将 local terminal 描述为无隔离并建议生产使用容器后端。因此本实现不复刻“local 同权限直接运行 + 路径规则”作为安全方案；把 Hermes 的根目录白名单思路用于受控文件工具，同时由 Linux bubblewrap 对技能进程强制只读系统根和受限挂载。来源：[Hermes 安全工作站指南](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/secure-hermes-on-a-work-machine.md)、[Hermes 安全文档](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/security.md)。

## 参考行为与映射

- Hermes `/learn` 将学习请求作为普通对话回合，使用当前智能体可用的读取工具收集资料，再通过技能管理工具保存；技能可以由当前会话内容、外部资料或用户描述生成。首期只实现当前会话来源，后续来源输入另行设计。参考 [Hermes Skills 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills) 与 `tools/skill_manager_tool.py`。
- Hermes `skill_manage` 提供受约束的 create/view/patch/file 操作，并有 agent-created 内容检查；本仓库已具备更强的平台解析、扫描和来源策略，因此沿用 `skill_manage` / `skill_save`，不复刻另一套磁盘 CRUD。参考 [Hermes skill_manager_tool.py](https://github.com/NousResearch/hermes-agent/blob/main/tools/skill_manager_tool.py) 与 [skills_guard.py](https://github.com/NousResearch/hermes-agent/blob/main/tools/skills_guard.py)。
- GenericAgent 将执行与经验积累放在 agent loop 周边；本仓库以持久 Run 和事件驱动 Native Runtime，故把显式学习作为一条新的用户消息，继续由标准 Run/ToolGateway 处理。参考 [GenericAgent agent_loop.py](https://github.com/lsdefine/GenericAgent/blob/a9a36b4/agent_loop.py)。
- 聊天页的标题和操作布局沿用 WeKnora `views/chat/index.vue` 与 `components/ChatHeader.vue`；Nexus 新操作留在平台聊天页，不依赖 WeKnora API。参考 [WeKnora 聊天页](https://github.com/Tencent/WeKnora/blob/e1f9a6166/frontend/src/views/chat/index.vue) 与 [聊天标题](https://github.com/Tencent/WeKnora/blob/e1f9a6166/frontend/src/components/ChatHeader.vue)。

## 交互流程

1. 工作台查询到会话关联的已发布智能体工具绑定；仅当 `skill_search`、`skill_manage` 和 `skill_save` 均已绑定、会话含消息、Run 不活跃、会话未阻塞且不是嵌入模式时显示“整理为技能”。
2. 点击后用本地化模板调用既有 `sendText`。请求本身成为可见、持久化的用户消息，Run 使用当前会话、智能体版本、授权、预算和运行时快照。
3. 指令要求智能体只从当前对话提炼可复用、已验证的步骤；排除一次性日志、猜测、秘密和可由工具/系统提示提供的规则。需先搜索现有技能避免重复，但首期不自动改写已有技能。
4. 智能体用 `skill_manage(create)` 创建草稿，再用 `skill_manage(view)` 读取正文并向用户展示。正文和工具结果作为不可信数据展示，不可绕过工具授权。
5. 指令要求在用户审阅并明确要求保存前不调用 `skill_save`。保存继续走现有 `requires_approval` 工具审批、`private.save`、内容扫描、版本检查和依赖构建。任何失败都通过现有工具结果/Run 错误呈现。

## 实现边界

- 前端用 `listAgents` 返回的 `published_version_id` 和 `resource_bindings` 对应当前会话版本，避免对所有智能体盲目显示入口。
- 不新增 HTTP 契约或数据库结构。客户端只提交普通对话消息；服务端继续以会话中的主体、空间及智能体版本决定授权。
- 嵌入式聊天保持无顶部操作入口；窄屏工作台标题栏操作允许收缩，保留标题、技能操作和产物入口可用。
- 模板按当前 locale 提供六种翻译，且内容明确说明这是新私有技能草稿、先展示正文、等待用户确认保存。

## 风险与处理

- 模型可能未按模板执行；是否能保存仍由 `skill_save` 的执行时授权及审批保护，草稿不会进入技能索引。
- 工具绑定可能在会话创建后被管理员撤销；实际工具调用仍由 Run 执行授权复核，按钮可见性只是用户体验，不构成权限。
- 长正文可能被工具结果投影截断；此时必须通过 `load_skill` / `read_skill_file` 的受控工具结果查看，不能声称用户已审阅未展示的内容。
- 当前首期只支持会话内材料；本地目录、URL、上传文档和后台自动复盘不包含在本变更。
