# 实施路线图

状态：2026-10-31。架构与模块设计见 [architecture.md](architecture.md)；本文件只记录最终计划的步骤、子步骤、验收与门禁。计划调整通过 OpenSpec 变更提案管理，不在此记录。

## 1. 原则

- 步骤按序号依次推进；一个步骤可包含若干子步骤，子步骤完成后打勾。
- 每个步骤结束时必须有可验收结果；验收未通过不进入依赖它的步骤。未通过的门禁须明确记录并告知用户。
- 外部依赖（PostgreSQL、真实模型、Codex/Claude 账号、观澜数据源）未验证前，不宣称对应功能可用。
- 涉及 API 契约、权限规则、持久化模型或 Runtime 行为变化的调整，先通过 OpenSpec 提案并获确认，再修改本路线图。
- 参考项目只借鉴设计并按需等价翻译，不整体嵌入。

## 2. 总览

| 序号 | 步骤 | 状态 | 依赖 | 门禁 |
|---|---|---|---|---|
| 1 | 工程骨架 | 已完成 | — | — |
| 2 | 平台底座 | 本地完成 | 1 | PostgreSQL 目标环境（暂跳过） |
| 3 | Native 运行时与引擎 | 进行中 | 2 | 真实模型供应商在线验收 |
| 4 | Codex 适配器 | 未开始 | 3 | Codex SDK 底层通道验证；Codex 账号 |
| 5 | Claude Code 适配器 | 未开始 | 4 | Claude Agent SDK 文档核对与版本锁定 |
| 6 | 知识库 | 进行中 | 3 | 外部向量库与 Neo4j 的真实环境验收 |
| 7 | 技能与 MCP | 未开始 | 3、6 | — |
| 8 | 沙箱后端 | 未开始 | 7 | 沙箱隔离验收 |
| 9 | 渠道与治理 | 未开始 | 3 | 各渠道接入条件 |
| 10 | 股票研究 | 未开始 | 6–9 | 观澜数据源逐接口验证 |

## 3. 步骤

### 1. 工程骨架

- [x] 锁文件安装、健康与能力端点。
- [x] 前端能力页与 worker 占位。
- **验收**：已通过。

### 2. 平台底座

- **目标**：身份、空间、授权、智能体、会话、幂等运行与事件的本地实现，并完成 PostgreSQL 目标环境验收。
- **参考项目**：WeKnora（Tenant、Session 忙碌控制、`suspend.go`、`approval/`、`agent_grant.go`）；Hermes Agent（`tools/approval.py`）；Octop（`infra/db/lease.py` 同行租约、`agents/middleware/token_quota.py` 用户 Token 额度、`agents/experts/publish.py` 专家共享）。队列使用 PostgreSQL Outbox，不参考 Redis 实现。
- **子计划**：
  - [x] 2.1 身份与空间：用户、外部身份、租户与成员关系。
  - [x] 2.2 认证：本地账号密码、服务端会话、企业微信绑定与登录。
  - [x] 2.3 授权：租户角色、菜单与 API 授权，智能体级授权，资源授权。
  - [x] 2.4 智能体与会话：智能体版本、Session、会话分叉。
  - [x] 2.5 运行：幂等 Run、事件、Outbox、租约领取、取消、审批与输入。
  - [x] 2.6 模型设置：供应商、个人与空间范围、加密 Key、连接测试；模型类型（对话、Embedding、ReRank、视觉、语音）与按类型的默认模型；未保存配置的连接测试（SQLite 已验证；PostgreSQL 随 2.9）。
  - [x] 2.7 记忆存储：`memory` 独立包，规则与存储端口分离。
  - [ ] 2.8 增量迁移：`action_grants`（与 `resource_grants` 分离）、`run_snapshots`（等待审批的版本化快照）。
  - [ ] 2.9 PostgreSQL 目标环境验证：迁移往返（含 `0a7c3e9d1b5f` 模型类型迁移）、并发领取、租约恢复、崩溃后 unknown 转换、同 Session 单活跃 Run。
  - [x] 2.10 派发账本（SQLite 已验证；PostgreSQL 随 2.9）：`runtime_epoch`（进程启动递增）、`session_admissions`（queued、started、unknown、terminal）；CAS 领取（rowcount 必须为 1）、按 `seq` 取队首、写入带 `owner_epoch` 的 fencing（过期 epoch 返回 `stale_epoch`）。单机用 SQLite 实现，多租户用 PostgreSQL 实现，接口相同。
  - [x] 2.11 启动恢复（SQLite 已验证；PostgreSQL 随 2.9）：旧 epoch 的 started 与执行记录标记为 unknown，会话阻塞，不自动重放；显式解除并记录审计。
  - [x] 2.12 会话快照与水位：版本化 JSON 快照（v2，只含数据）；保存快照带预期水位，不一致则拒绝；消息写入递增水位；未知版本拒绝。v1 迁移函数暂缺：仓库中没有持久化过 v1 数据（SQLite 已验证；PostgreSQL 随 2.9）。
- **验收**：本地（SQLite）测试通过；2.9 目标环境通过并记录环境、版本与结果。2.9 暂跳过（用户决定当前版本使用 SQLite）。2.10 至 2.12 的单机实现与多租户实现共用契约测试。
- **依赖**：1。

### 3. Native 运行时与引擎

- **目标**：Native 智能体可运行并在对话工作台中使用；锁定运行时契约，把引擎拆分为独立组件并补齐功能，覆盖运行编排、回合执行、上下文、完成判断、工具、记忆、技能、取消、恢复和预算。行为与参考项目对齐。
- **参考项目**：GenericAgent（`agent_loop.py`、`ga.py`、`memory/`）；WeKnora（`engine.go`、`suspend.go`、`compaction/`、`tools/`）；OpenClaw（`run-loop.ts`）；Dify（`fc_agent_runner.py`）；n8n（`executeBatch`）；DeepSeek Harness（`agent-loop`、`spill`）；DeepSeek Super-agent（Watchdog、Chain of Recall、异步工具，设计文章与原型）；Hermes Agent（`memory_tool.py`）；LobeHub（`context-engine`）；RAGFlow（`evidence_registry.go`）；DeerFlow（`agents/memory/`）；Octop（`infra/agents/middleware/model_failover.py` 健康感知故障转移、`agents/settings/runtime_limits.py` 智能体运行参数映射、`agents/settings/tool_catalog.py` 工具目录与禁用策略、`gateway/steer/` 运行中追加指令）；octop-harness（`compaction.py` 与 `middleware/summarization_limits.py` 压缩时不重发超大历史、`middleware/tool_order.py` 稳定工具顺序以复用提示缓存、`middleware/model_retry.py` 重试策略、`middleware/model_settings.py` 生成参数、`middleware/conversation_mode.py` 回合级工具白名单、`usage.py` 与 `context_usage.py` 用量归一与上下文占用、`protocols/think_splitter.py` 流式拆分思考内容）；octop-memory（L0 原始事件 → L1 候选 → L2 原子卡片 → L3 实体页 → L4 审计日志的分层；`pipeline/promotion/checks.py` 候选晋升前的五项检查、`pipeline/recall/` 召回路由、预算、注入前抑制与重排、`domain/retention.py` 按来源的保留规则）。
- **子计划**：
  - [x] 3.1 基础闭环：流式模型、授权工具、取消、等待输入、检查点、SSE、对话工作台。
  - [ ] 3.2 真实 OpenAI-compatible 供应商在线验收（用户在设置页配置后）。
  - [x] 3.3 运行时契约：`AgentRuntime` 端口、`RuntimeCapabilities`、`RunRequest` 与 `RunContext`（`nexus_core.runtime.port`）；删除未使用的旧 `contracts.AgentRuntime`。`RunEvent` 未引入：事件仍以 `(kind, payload)` 经存储端口传递，改动需另行提案。
  - [x] 3.4 运行编排 `RunOrchestrator`：生命周期、取消、预算、事件持久化、租约检查；由 `NativeEngine` 改名而来，实现 `AgentRuntime`，不保留兼容门面（worker 与测试已同步）。
  - [x] 3.5 单回合执行 `TurnExecutor`：组装请求、调用模型、收集流式响应并解析结果（预算计数与 model.before/after 钩子仍由编排器负责）。
  - [x] 3.6 上下文装配 `ContextAssembler`：Run 开始时冻结工具定义（摘要校验，变化则 `context_prefix_changed`）、回合视图、压缩结果作为 `context.compacted` 事件写入；证据句柄沿用既有外置机制。
  - [x] 3.7 完成判断 `CompletionJudge`：截断续写（最多 `max_continuations` 次，默认 2，发出 `answer.continued`）、空响应有限次重试、重复内容停滞判定、不完整工具调用不执行、最后一轮禁用工具（工具定义为空并追加提示；模型仍返回的调用一律拒绝执行）。
  - [x] 3.8 工具调度 `ToolDispatcher`：结果投影、审批挂起、错误预算、终态与续写。参数 schema 校验与授权网关复核由工具网关完成；大输出 Spill 沿用既有 P2 机制；同一回合按声明顺序，有副作用的工具不并发。
  - [x] 3.9 工具定义与网关：`ToolDefinition` 新增 `risk_level`（low/medium/high）与 `required_capabilities`（已声明，执行前的能力检查随沙箱接入实现）；网关每次调用复核授权；处理器可协作取消。
  - [x] 3.10 内置平台工具：工作检查点更新（仅由成功的工具结果驱动）、待办（`todo`，`list`/`set`，状态存于 Run 的 progress 状态，Run 结束释放，不做会话级持久化）、询问用户（`wait_input`）；知识检索与记忆读取以接口形式预留，实现随第 6 步完成。
  - [ ] 3.11 记忆接入：会话开始时冻结已发布的用户事实快照进入提示；模型写入只产生草稿，草稿在审核前不进入提示；所有写入携带来源与作用域，并保留 Run、Session 等引用 ID，为后续链式召回预留。
    - 进展（提案 2026-11-06-memory-evolution）：抓取质量、画像常驻块与容量行、使用统计与排序、对话内草稿确认、整理合并草稿、数据保留、历史会话检索已完成；向量召回、每轮主动召回、抓取用量、兴趣主题、外部提供方端口也已完成；记忆设置页与智能体编辑器开关已接入；文档亲和度等待第 6 步知识检索后实施（同模型复盘已移出范围）。
  - [ ] 3.12 技能指令加载：按绑定读取已发布技能的名称与简介，正文与资源按需加载（渐进披露）。技能管理、来源检疫与发布审核见第 7 步。
  - [ ] 3.13 取消与等待：取消信号在模型流与工具调用处已检查；等待输入后在同一 Run 中幂等继续已有测试。未完成：沙箱等待点的取消检查，随沙箱接入完成。
  - [ ] 3.14 挂起恢复：审批一次性消费、配置哈希绑定、恢复时主体与租户校验、已完成调用不重放、每次调用重新授权已核实。未完成：运行进度（progress）没有版本标记，恢复前无法校验进度格式版本，需另行提案。
  - [x] 3.15 预算与钩子：逻辑回合、模型请求（含重试，`max_model_attempts`，0 为按回合与重试次数推导）、活跃耗时（不含等待用户时间）、token 与错误分别计数并持久累计；agent、turn、model、tool 的 before/after 钩子只接收稳定元数据，异常隔离。
  - [ ] 3.16 运行时契约测试：同一组用例（文本流、多工具、审批拒绝、取消、超时、恢复）按契约断言统一终态与事件序列。
  - [ ] 3.21 性能验收：上下文与持久化的默认值切换以基线为依据（固定会话集上的输入 token、`cached_tokens`、模型耗时、事务数、`run_events` 条数、准备阶段耗时），并以 evals 比较任务完成与事实一致性（追问依赖上一轮工具结果的样例）；下降则先补充回答要求再上线。未完成前相关默认值保持保守。
  - [x] 3.22 用户组织管理：组织树（集团、子公司、部门统一为节点，层级不限）、人员归属（一人一个主节点）、空间绑定节点（子树可见，人员不自动入空间）、从绑定子树显式选人加入空间；平台管理员标识（`users.is_platform_admin`）控制组织管理，`nexus_api.cli set-platform-admin` 设置。（SQLite 已验证；PostgreSQL 随 2.9。）
  - [x] 3.20 忙时排队：同会话新 Run 以 FIFO 排队（202 与 `queue_position`），队列上限 32（409 `session_queue_full`），非队首延后投递；取消排队中的 Run 释放位置。默认不打断。（SQLite 已验证；PostgreSQL 随 2.9。）
  - [ ] 3.17 执行模型：每个 Run 新建执行对象，Run 结束释放；工具注册表进程级共享（已完成）；模型客户端的连接池按来源进程内共享（已完成，凭据仍每 Run 解析）；不按会话缓存执行对象。
  - [x] 3.18 会话快照与终态保存：成功、失败、取消、中断均在 Run 终态写入路径中保存 v2 快照（同一事务，而非运行器 `finally`）；仍运行的工具调用标记 `interrupted`；未知版本拒绝。
  - [x] 3.19 投影缓存：历史消息行以 `(session_id, watermark)` 为 key，无需失效；LRU、空闲 TTL、单条目字节上限；缓存不含授权结果，每次运行与每次工具调用都重新检查权限。（默认值为估计值，待真实负载校准。）
  - [ ] 3.23 运行监督 Watchdog：独立于 Run 的外部监督循环，检查长任务是否有实质进展、是否偏离目标；只能提示、暂停或请求人工介入，不直接修改执行结果。依赖 3.15 的活跃耗时与 3.13 的取消。**当前进度**：空闲与重复调用两条规则、`run.watchdog_alert` 事件、`attention_required` 与确认接口已实现（SQLite 已验证）；工作台提示与操作待办（见 openspec/changes/2026-11-04-run-watchdog）；回合数规则随 3.15；"偏离目标"判断未纳入。
  - [ ] 3.24 异步工具与推测执行（待评估）：耗时工具以后台任务启动，结果作为新事件回到会话；推测性工作只允许准备草稿、不交付副作用，受额度与授权约束。进入实施前须复核与 3.8（副作用工具不并发）和 3.9（网关复核）的一致性，并单独提案。
  - [ ] 3.25 智能体与模型设置界面（`openspec/changes/2026-11-05-weknora-agent-tool-model-settings`）：智能体列表与编辑器（基本信息、提示词、模型与生成参数、工具配置）、内置工具目录、智能体级温度与思考强度（运行时覆盖模型档案选项）、归档与复制、设置 → 模型管理接入平台接口。后端与单元测试已完成；完整前端构建与浏览器验证待在内存充足的环境执行。
  - [x] 3.26 工具调用加固（`openspec/changes/archive/2026-11-06-tool-call-hardening`，已实施）：参数容错（JSON 修复、类型转换、字段级校验错误）；工具定义按名排序；头尾截断与每轮工具输出总预算；工具输出注入扫描；工具循环检测（`tool_loop_detected`）；风险四级与智能体访问级别；审批「本会话允许」（`action_grants`）；执行前参数守卫（`CRITICAL` 硬拒绝、`HIGH` 必须审批）。
  - [ ] 3.27 工具扩展（`openspec/changes/2026-11-07-tool-expansion`，实施中）：工具分组与两层门控（部署可用性 × 智能体开关，`sandbox`、`web`、`collab`、`schedule`、`media` 默认关闭）；按调用调度（并行 / 独占 / 按 key 串行）；`sandbox` 组六个工具与沙箱后端（真实 Docker 验收待运行）；`tool_search` 渐进加载与 schema 清洗；`web_search` / `web_fetch`；`delegate_task`；`cronjob_*`；`vision_analyze`。Wiki 组的门控已就绪，工具随知识库 K6.1。编辑器已有工具分组开关（不可用原因、待实现标记）与沙箱档位选择；定时任务有 REST（`/schedules`）与 WeKnora 自动化页适配的界面（管理员可看全部并暂停他人任务，不支持的调度类型与策略标「待实现」）；前端均未在浏览器验证。产物登记与下载接口、产物库页面已完成（`/outputs` 在 Run 结束时复制登记，授权下载与审计；页面复用 WeKnora 产物库，未在浏览器验证）。未完成：真实 Docker 验收、`pnpm build` 与浏览器测试（技能脚本已由技能演进改走 `exec_skill`）。
  - [ ] 3.28 Run 事件通道与部署模式（`openspec/changes/2026-11-07-run-event-streaming`，实施中）：`database` / `redis` / `memory` 三个事件通道后端；持久事件提交后发布，`message.delta` 在 redis / memory 下不入库，回合结束写持久事件 `message.completed`；订阅管线（重放、去重、补读、`stream.resync`）与异步 SSE；取消唤醒、生产者围栏、会话活动 Run 标记与 `live-run` 接口；`embedded` 部署模式；每租户 / 用户活动会话上限与后台模型调用按模型限流。未完成：压测对比数据、故障注入验收（Redis / worker / 客户端）、前端 `vue-tsc` 与浏览器测试。
  - [ ] 3.29 Worker 并发执行与 unknown 会话恢复入口（`openspec/changes/2026-11-07-worker-concurrency`，实施中）：一个 worker 在一个事件循环里以协程并发执行最多 `[worker].max_concurrent_runs` 个 Run，同步数据库调用走专用线程池，API 与 worker 的线程池和连接池可配置，SQLite 并发写入排队；嵌入模式改为单线程单循环；`unknown` 会话的列表与解除接口、命令行，定时任务会话启动恢复时自动解除，可选的无副作用自动解除，前端提示条。未完成：知识库工具与凭据解析里残留的循环内数据库读取、PostgreSQL 上的压测、`pnpm build` 与浏览器测试。
- **验收**：3.2 真实供应商验收通过；契约测试全部通过；既有 Native 测试保持通过；没有隔离后端时执行类工具不可见；记忆草稿不进入提示。
- **依赖**：2。

### 4. Codex 适配器

- **目标**：以 `openai-codex` SDK 管进程，事件与审批经 app-server 协议获取。
- **参考项目**：Hermes Agent（`agent/transports/codex_app_server.py`）；官方 `openai-codex` SDK 与 App Server 文档（无开源参考，实施时重新核对）；Octop（`infra/agents/settings/acp.py` 与出站 ACP Runner：经 Agent Client Protocol 委派 Codex，仅参考协议形态）；octop-harness（`acp/` 客户端、服务与权限处理，`builtin/tools/acp_runner.py` 委派工具）。
- **门禁**：确认 SDK 是否暴露底层 JSON-RPC 通道。结论决定连接方案，方案变更通过 OpenSpec 记录。
- **子计划**：
  - [ ] 4.1 能力探测（版本、`initialize` 能力）。
  - [ ] 4.2 会话映射（`runtime_session_bindings`）、`thread/start`、`thread/resume`、`thread/fork`。
  - [ ] 4.3 事件映射与终态映射。
  - [ ] 4.4 审批桥：命令与文件变更审批转为 `approval.requested`；`acceptForSession` 先经 `action_grants` 批准。
  - [ ] 4.5 取消（`turn/interrupt`）与 `interrupted` 终态。
  - [ ] 4.6 平台 MCP 服务 endpoint 长期令牌（与第 7 步共用）。
  - [ ] 4.7 测试：假 app-server 协议测试；真实 Codex CLI 集成测试（账号可用时）。
- **验收**：第 3 步的契约测试集在 Native 与 Codex 上终态一致；审批可拒绝；取消生效；原生文件与 shell 限制在工作区内；无法约束的能力标记 unverified 且不可绑定。
- **依赖**：3；Codex 账号与 CLI 版本。

### 5. Claude Code 适配器

- **目标**：以 `claude-agent-sdk` 封装 `ClaudeSDKClient`。
- **参考项目**：官方 `claude-agent-sdk`（无开源参考实现，实施前核对官方文档）；Octop（出站 ACP Runner 委派 Claude Code，仅参考协议形态）；octop-harness（`acp/` 客户端、服务与权限处理，`builtin/tools/acp_runner.py` 委派工具）。
- **门禁**：读取官方文档，核对 `can_use_tool`、hooks、`resume`、`fork_session` 的实际行为并锁定版本，结果同步更新 [architecture.md](architecture.md) 第 2.4 节。
- **子计划**：
  - [ ] 5.1 `can_use_tool` 审批桥；`disallowed_tools` 禁用原生工具。
  - [ ] 5.2 会话 resume 与 fork。
  - [ ] 5.3 工具桥（复用第 4 步的 MCP 服务）。
  - [ ] 5.4 测试：复用第 3 步的契约测试集。
- **验收**：契约测试通过；原生工具禁用测试通过；未核对的能力保持 unverified。
- **依赖**：4；本机 Claude Code CLI 与账号。

### 6. 知识库

- **目标**：完整保留 WeKnora 知识库功能（库类型、索引策略、向量库与存储后端配置、解析引擎、FAQ、Wiki、图谱、标签、文件夹、数据源等），在此基础上参考其他项目增强；图谱支持 GraphRAG。实施提案 `openspec/changes/2026-11-06-knowledge-base`。
- **参考项目**：WeKnora（功能基线、向量库注册、FAQ、Wiki、Neo4j 图谱、数据源）；RAGFlow（`internal/agentic_rag/` 证据登记与检索工具、`internal/service/graph/` GraphRAG 检索）；Octop（`infra/knowledge/`：能力门控、作业恢复、机器可读引用）；FastGPT（训练队列、同义词）；Dify（元数据过滤、重排）。
- **子计划**：
  - [ ] 6.0（K0）前端保留 WeKnora 全部知识库入口，后端能力目录逐项返回已实现或待实现，未实现项标记「待实现」且不可提交。
  - [ ] 6.1（K1）文档库核心：库、文档、不可变版本、文本块、可恢复作业；上传去重与版本切换；向量库与存储后端注册；Pre-Filter 后混合检索与降级；`search_knowledge`、`read_document`、`list_documents`（接入第 3.10 步预留接口）；证据登记 `[ID:n]`；管理页、检索测试、评估集。
  - [ ] 6.2（K2）图谱：图存储可配置（内置关系表、Neo4j）；模式 `entity`、`graphrag_light`、`graphrag_general`；库级构建任务、版本切换、有界图检索与降级。
  - [ ] 6.3（K3）FAQ 库。
  - [ ] 6.4（K4）解析引擎规则、Office 文档、分块策略与父子分块、OCR / VLM / ASR。
  - [ ] 6.5（K5）标签、文件夹、摘要、提问生成、库画像、重排、元数据过滤、同义词、结构导航工具。
  - [ ] 6.6（K6）Wiki 库。
  - [ ] 6.7（K7）数据源同步框架与连接器（连接器随账号逐个接入，未接入的转第 9 步）。
- **验收**：同一智能体可绑定多个库；无权资源不经关键词、向量、图谱或降级路径泄漏；基础检索不依赖图谱；撤权、删除、索引重建同步生效；图存储故障时降级可见；前端无未接入的 404，未实现项均有标记。
- **依赖**：3。
- **向量库**：首批实现 SQLite、PostgreSQL（pgvector）、Qdrant、Elasticsearch、Milvus；只有 SQLite 在本地测试，其余四种在真实环境验收前标「未验证」。其他引擎标「待实现」。

### 7. 技能与 MCP

- **目标**：版本化技能、来源检疫、依赖校验；MCP 按工具启用。
- **参考项目**：Hermes Agent（`skills_guard.py`、`skills_hub`）；DeerFlow（`skills/`）；WeKnora（`approval/mcp_risk.go`）；Octop（`infra/connectors/custom_mcp.py` 自定义 MCP 服务、`mcp_tool_cache.py` 按用户的工具缓存与指纹、`connectors/oauth/`、`infra/skills/` 安装与归档）；octop-harness（`mcp.py` 与 `middleware/mcp_tools.py` 按请求过滤 MCP 工具、`middleware/mcp_tool_error.py` MCP 错误转为失败的工具结果、`middleware/skill_filter.py` 技能禁用与过滤、`middleware/tool_search.py` 工具渐进加载、`plugins/` 插件清单与加载）。
- **子计划**：
  - [ ] 7.1 技能：版本、`SKILL.md` 与资源、依赖声明、发布前依赖校验、来源检疫、草稿与审核发布。
    - 已完成（提案 2026-11-04-skill-scripts）：解析与版本、内联加载、绑定与发布前依赖校验、脚本执行（子进程，仅开发门禁）、审批与审计、管理员发布与列表接口、内置技能导入（`import_builtin`，以 `builtin` 来源发布 `skills/` 目录下的技能，重复导入报告 `unchanged`，同名已安装技能不能替换；仅服务层函数，尚无 API 或命令行入口）。
    - 已完成（提案 2026-11-07-skill-evolution，S1 后端）：系统租户与内置技能和工具（所有空间可见可分配、空间可停用、平台管理员接口与命令行导入、启动同步）；规则扫描器与放行矩阵（确认放行、审计、重扫）；YAML 前置块、名字规则、`model_invocable` / `user_invocable` / `execution`。
    - 已完成（S2，同提案）：沙箱档位（`local` / `docker` / `bwrap`，默认 `local` 且仅开发模式可用，智能体按名选择，可用性与验收按档位）；技能只读投射进沙箱；结构化的 `exec_skill`（取代 `run_skill_script`，脚本无需声明）；`sandbox_exec` 增加 `stdin`；`execution` 策略。
    - 已完成（前端）：智能体编辑器里内置工具与技能标「内置」、本空间停用 / 恢复、技能分区（绑定、缺工具提示、新版本提示）、沙箱档位选择。
    - 已完成（S3，同提案）：技能 zip（安全解包、规范打包、导出）、语法验证关、上传与远程来源安装（五类来源、受保护下载）、依赖环境构建与安装状态机（docker / bwrap / local 构建器、worker 认领与周期清理、重试与停止）、编辑器的安装对话框。
    - 已完成（S4，同提案）：私有技能与草稿、`skill_manage` / `skill_save` / `skill_rollback`、回退与归档、「我的技能」对话框。
    - 已完成（S5，同提案）：`skills:submit`、提交与审核、管理员直接共享、编辑器的共享按钮与审核对话框。
    - 已完成（提案 `2026-11-08-toolbox`）：工具箱页（技能库 / 我的技能 / 审核 / 安装，内置工具目录与启停；MCP 与浏览器连接标「计划中」，等对应后端）。
    - 已完成（提案 S6 的 6.4 与 6.2）：`skill_search`；使用记录（次数与最近使用，只记录展示）。
    - 未完成：前端新对话框的浏览器实测、完整类型检查与构建；S2、S3 在真实 Docker 与 bwrap 上的验证（构建器与挂载只有命令行单元测试）；ClawHub 地址与 GitHub / GitLab 真实压缩包格式的联网验证；会话中追加差异说明消息；技能包、使用记录的自动归档、凭据、LLM 安装智能体等（提案 S6 的其余项，各自开始前补设计并确认）；按用户 PostgreSQL 验证。
  - [ ] 7.2 MCP 客户端：发现工具、按工具启用、凭据引用、高风险工具审批。
    - 接入约束（提案 2026-11-06-tool-call-hardening 决定 3，见 `docs/architecture.md` 2.7）：注册名哈希防撞名、风险只升不降、执行时复核目录、按用户缓存工具并用指纹失效、`McpError` 与输出 schema 错误分类、外部数据前缀、按供应商清洗 schema、`tool_search` 渐进加载。
    - 已完成（提案 2026-11-08-mcp，1.1–1.8）：持久化与领域服务、三种传输的发现 / 调用、按工具启用、风险只升不降与审批、指纹缓存与 `config_epoch`、Run 快照绑定与执行前复核、OAuth 授权码流（动态注册 + PKCE，令牌按主体加密存储与刷新，401 恰好一次重试）、管理 API 与公开回调。
    - 未完成：前端工具箱 MCP 标签；集成测试（假 MCP 服务、OAuth 端到端）。
  - [ ] 7.3 MCP 服务端：无状态 endpoint，每次调用复核权限。
    - 已完成（同提案，2.1–2.6）：`mcp_endpoints` 表、endpoint 长期令牌签发 / 解析 / 撤销（SHA-256 哈希存储）、`EndpointMCPServer` 无状态只读工具面、`/mcp/{endpoint_id}` 挂载与 Bearer 鉴权、管理 API。
    - 未完成：前端工具箱 endpoint 管理界面（依赖第 4/5 步外部 Runtime 适配器接入只读工具面）。
- **验收**：两个技能与授权 MCP 工具协同执行；缺失权限或依赖时明确报错并阻止发布；撤权后下一次调用拒绝；产物可按授权下载。
- **依赖**：3、6。

### 8. 沙箱后端

- **目标**：评估候选后端，选择通过隔离验收的实现。
- **参考项目**：DeerFlow（`sandbox/`）；Hermes Agent（`tools/environments/`）；DeepSeek Harness（接缝设计）；FastGPT（`agent-sandbox`，仅参考）；Octop（`infra/backend/` 可插拔工作区后端：本地、Docker、PostgreSQL、对象存储，`resolver.py` 组合路由，与控制面数据库分离）；octop-harness（`backends/docker_sandbox.py`、`backends/bwrap_shell.py` 目录隔离、`backends/local_shell.py` 虚拟路径转换、`backends/composite.py`、`backends/probe.py` 写读删连通探测、`security/ssrf.py` 出站请求 SSRF 防护）；octop-browser（`cdp/` 纯 asyncio CDP 客户端与进程管理、`dom/builder.py` 面向模型的分层 DOM、`profile.py` 会话持久化、`idle.py` 空闲回收、`mcp_server.py` 以 MCP 暴露浏览器操作）。
- **子计划**：
  - [ ] 8.1 `CommandExecutorPort` 与 `FileStorePort` 的实现（候选：docker、ssh）。
  - [ ] 8.2 租约、虚拟路径映射、原子写入、产物收集。
    - 执行类工具约束（提案 2026-11-06-tool-call-hardening 决定 3，见 `docs/architecture.md` 2.9）：按参数判断能否并行、同路径写入串行化、shell 类工具经过参数守卫。
  - [ ] 8.3 隔离验收：CPU、内存、时间、输出限制；网络隔离；用户隔离；清理；崩溃后残留检查。
- **验收**：隔离验收全部通过后，才注册任意代码与文件写入工具；未通过则工具不可见。
- **依赖**：7。
- **待确认**：部署环境与可用的容器运行时。

### 9. 渠道与治理

- **目标**：IM 渠道接入与运行评估。
- **参考项目**：LobeHub（`chat-adapter-*` 的组织方式）；DeepSeek Super-agent（事件两级过滤、Thread 订阅）；Octop（`infra/gateway/` 多 IM 通道归一为同一处理链路、`gateway/hitl/` 渠道内审批、`infra/cron/` 定时任务）；octop-gateway（`channel.py` 渠道抽象、`manager.py` 按会话合批、`constraints.py` 平台限制与限流、`push_routing.py` 主动推送路由、`channels/wecom.py`、`channels/feishu.py`、`channels/dingtalk.py`、`channels/telegram/delivery.py` 只在明确拒绝时重试、`channels/telegram/policy.py` 先准入再取媒体）。
- **子计划**：
  - [ ] 9.1 企业微信优先，随后微信、QQ：消息标准化、身份映射、会话映射、去重、鉴权、回复限制、重试。
  - [ ] 9.2 运行评估集：固定任务、检索引用正确率、技能选择准确率。
  - [ ] 9.3 记忆与技能草稿的审核流程。
    - 记忆部分已完成（2026-11-06）：我的记忆页审核草稿（可改标题与重要度、看证据与冲突/相似/合并提示），对话内确认卡片；技能草稿审核未做。
  - [ ] 9.4 外部事件触发（待评估）：渠道消息、定时采集等事件先经程序规则过滤，再由模型判断是否行动；同一话题的后续事件可直接投递给已分配的会话，减轻中心调度负载。
- **验收**：授权用户从渠道发起任务并获得可追溯回复；其他用户不能混入会话；评估集可重复运行。
- **依赖**：3；企业微信可在第 7 步后提前。
- **待确认**：各渠道接入方式与账号条件。

### 10. 股票研究

- **目标**：观澜数据平台与股票研究技能合并交付。
- **参考项目**：TradingAgents（`graph/setup.py`、`memory/reflection.py`）；daily_stock_analysis（分工与分析深度分级，未深读）；Qlib（训练与推理分离，未深读）。
- **子计划**：
  - [ ] 10.1 数据适配器与调度：行情、交易日历、财务、公告、热点、龙虎榜；逐接口验证；失败重试与降级标注。
  - [ ] 10.2 数据时点与来源：每条数据保留 provider、获取时间、数据时点、复权口径。
  - [ ] 10.3 领域工具通过公共协议注册。
  - [ ] 10.4 研究流程：步骤是否必选在本子计划确认。
  - [ ] 10.5 研报与规则入库审核，版本化。
  - [ ] 10.6 回测（`guanlan/backtesting`）：复权、交易成本、停复牌、退市与未来信息泄漏。
- **验收**：报告中每个数值与结论可追溯到来源、时点与版本；无权数据不可检索或读取；回测记录基准、成本与时间段；至少一个数据源通过逐接口验证并有失败与降级测试。
- **依赖**：6–9。
- **实施前需用户提供**：观澜数据源账号或授权信息；目标市场、标的范围、历史回溯与更新频率；研报与规则样例。
- **启动前**：通过 OpenSpec 提案并获用户确认。

## 4. 验收门禁汇总

| 门禁 | 所属步骤 | 状态 |
|---|---|---|
| PostgreSQL 目标环境测试 | 2.9 | 暂跳过（用户决定） |
| 真实模型供应商在线验收 | 3.2 | 待用户配置 |
| 运行时契约测试 | 3.16 | 待执行 |
| Codex SDK 底层通道验证 | 4 | 待执行 |
| Claude Agent SDK 文档核对与版本锁定 | 5 | 待执行 |
| 沙箱隔离验收 | 8 | 待执行 |
| 前端构建与浏览器统一验证 | 第 8 节 | 最后统一执行 |
| 观澜数据源逐接口验证 | 10 | 待用户提供账号 |

## 5. 测试与评估

- 每个步骤运行涉及的单元与集成测试，以及前端构建（`npm run build`）；聊天交互变化时运行 `npm run test:browser`。
- 涉及鉴权、取消、重复投递、资源删除或恢复时，增加对应集成场景。
- 评估（`evals/`）：固定智能体任务、检索与引用、技能工具选择、Runtime 能力契约。
- 策略回测与软件回归分开记录。
- 未执行的测试在交付说明中列明，不以部分通过代替完整验收。

## 6. 风险

| 风险 | 影响 | 应对 |
|---|---|---|
| Codex app-server 为实验性或版本变化快 | 适配器失效 | 锁定版本；能力探测；契约测试 |
| Claude SDK 的权限与 resume 行为与摘要不一致 | 审批或会话错误 | 第 5 步前读官方文档，未核对不承诺 |
| 外部 Runtime 原生工具越权 | 数据泄露或误操作 | 工作区隔离、禁用原生工具；无法约束则不允许绑定 |
| 账号或模型不可用 | 无法验收 | 由用户提供；未验收不宣称 |
| 范围过大 | 交付延迟 | 严格按步骤验收推进；Native 与 Codex 先行 |
| Native 迁移引入的复杂度 | 行为回归 | 组件测试与契约测试；拆分后逐组件验证 |
| 仅在 SQLite 上验证 | PostgreSQL 环境下行为未知 | 部署到 PostgreSQL 前补做 2.9 |

## 7. 待用户提供（按步骤）

- 2.9：目标 PostgreSQL 环境（当前暂跳过）。
- 3.2：真实模型供应商的协议、地址与 Key（通过设置页配置）。
- 4：Codex 账号、可用模型清单与 CLI 版本。
- 5：Claude Code 账号与本机 CLI 环境。
- 6：PostgreSQL（pgvector）、Qdrant、Elasticsearch、Milvus、Neo4j 的测试环境（用于真实验收）。
- 8：容器运行时或远程执行环境。
- 9：各渠道的账号与接入条件。
- 10：观澜数据源账号、市场范围、历史范围与样例材料。

以上条目未提供前，对应步骤停在门禁处，不影响其他步骤的本地实现。

## 8. 最后统一验证

以下验证需要内存充足的机器（本机 1 GB 级内存时 `pnpm build`、`vue-tsc` 与 Vite 依赖预构建会被 OOM 杀掉，2026-11-11 已复现），或真实的外部环境。各步骤的功能先按本地可验证的范围实现并标注“未在浏览器验证”，在全部功能完成后一次性执行本节；未执行前不得把对应任务标为完成，也不得归档对应变更。

- **前端构建与类型**：`pnpm build` 与全量 `vue-tsc --build` 通过；前端单元测试全量通过。
- **浏览器测试**：文档里写的 `pnpm test:browser` 目前在 `apps/web/package.json` 中并不存在，也没有 Playwright 依赖，执行本节前先补上脚本与依赖（后端用临时数据库、开发认证模式，避免碰开发库）。逐页核对：无 404、无控制台报错、未实现项均有“待实现”标记。
  - 知识库（提案 `2026-11-06-knowledge-base` K0.4、K1.9）：列表与详情、FAQ、Wiki、图谱、标签、文件夹、图片库、数据源、共享、活动、设置页四项；创建与编辑、上传与重试、块预览、检索测试、共享与引用渲染、智能体编辑器知识库分区。
  - 工具扩展（`2026-11-07-tool-expansion`）：产物库页面（4.6.6）、聊天页产物卡片（4.6.7）、自动化页、智能体编辑器的工具分组开关与沙箱档位。
  - 其他提案遗留的浏览器项：`2026-11-04-native-run-workbench` 4.3、`2026-11-04-weknora-chat-dialog` 5.3 与 7.10、`2026-11-05-weknora-agent-tool-model-settings` 4.4、`2026-11-02-session-management` 前端、`2026-11-07-worker-concurrency` 4.3。
- **真实环境验收**：
  - 沙箱：真实 Docker 上运行 `python -m nexus_worker --sandbox-check` 并保存报告（3.7，本机当前用户无 Docker 权限）；开启沙箱组的智能体经 worker 端到端（4.9）。真实 bwrap 已于 2026-11-11 在本机验收通过（3.8），其放宽的进程数准入条件待确认。
  - 知识库：PostgreSQL（pgvector）、Qdrant、Elasticsearch、Milvus（K1.2c）、Neo4j（K2.7b）、视觉与语音模型（K4.2b）、重排模型（K5.3c）、Wiki 合成质量（K6.2）。
  - PostgreSQL 上的迁移与部分唯一索引（2.9）。
- **收尾**：上述通过后，同步各提案规格并归档：`2026-11-07-tool-expansion`（9.1–9.3）、`2026-11-06-knowledge-base` 等。
