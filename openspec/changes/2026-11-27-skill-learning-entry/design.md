# 设计：当前会话整理为技能

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
