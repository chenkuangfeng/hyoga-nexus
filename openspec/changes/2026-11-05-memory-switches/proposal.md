# 长期记忆开关：空间、个人、智能体三级，并按 WeKnora 接入记忆设置页

## 状态

已确认（2026-11-05）：决定 1–4 全部采用推荐方案。父提案：`openspec/changes/2026-11-02-weknora-parity/`（`tasks.md` 第 51 行「记忆审核与快照……在对齐后的界面中体现」、能力对照表第 23 项「缺按空间的设置入口」）。记忆规则与存储沿用 `openspec/changes/2026-11-01-memory-optimization/`，本提案不改动其规则。

## 原因

- Nexus 目前没有「是否使用长期记忆」的开关。只要会话所有者有已发布条目，每个 Native Run 都会注入记忆索引（`runs/preparation.py` 调用 `snapshots.session_index`），智能体只要绑定了记忆工具，就能读取和提议记忆。
- 唯一的开关是自动抓取（`GET/PUT /tenants/{tenant_id}/memory-capture`，表 `memory_capture_settings`）。它只控制后台抽取，而且前端没有入口，只能直接调用 API。
- 前端设置页的「记忆」（空间）和「我的记忆」（个人）是 WeKnora 副本（`MemoryWorkspaceSettings.vue`、`MemorySettings.vue`），调用的是 Nexus 不提供的 `/api/v1/memory/*`。它们不在 `config/phase1.ts` 的已实现分区里，所以只显示占位页。
- 路由使用的智能体编辑器 `NexusAgentEditorModal.vue` 没有记忆开关。WeKnora 副本 `AgentEditorModal.vue` 有 `memory_enabled` 开关，但不在路由上，后端也不读取这个值。

参考源码：WeKnora 固定版本 `e1f9a6166`（本地副本 `/project/opensource/knowledge-base/WeKnora`）。
- 三级开关：`internal/types/memory.go`（`MemoryConfig.Enabled`、`WriteMode`、`MemorySubject.Enabled`、`ApplyAgentMemoryPreference`）、`internal/types/agent.go:121`（`MemoryEnabled *bool`，`nil` 表示继承）。
- 生效判断：`internal/application/service/memory/service.go` `enabledScope`。依次检查空间、智能体、个人，任一项关闭就视为不可用。
- 工具跟随开关：`internal/application/service/agent_service.go:1325`。记忆可用时才注册 `search_memory`；即使工具允许列表里还写着它，记忆关闭时也会被移除。
- 界面：`frontend/src/views/settings/MemoryWorkspaceSettings.vue`、`MemorySettings.vue`、`views/agent/AgentEditorModal.vue`（基本信息里的「长期记忆」开关）。

## 范围

### 范围内

1. **三级开关与生效规则**（后端）
   - 空间开关：由空间 owner 或 admin 设置，同时设置写入方式（`explicit` 仅显式提议，或 `auto` 允许自动提炼）。
   - 个人开关：成员自己设置，只影响本人在该空间的记忆。
   - 智能体开关：`budgets.memory.enabled`。不设置表示继承，设为 `false` 表示该智能体不使用记忆；随版本发布冻结。
   - 生效规则：空间开 **且** 个人开 **且** 智能体未关闭，记忆才可用。只要有一级关闭，本次 Run 就按「记忆关闭」处理（见决定 2）。
2. **接口**（需确认，属于 API 契约变化）
   - `GET/PUT /api/v1/tenants/{tenant_id}/native/memory-settings`：空间设置。成员可读，owner 或 admin 可写，写入时记审计 `memory.space_settings`。
   - `GET/PUT /api/v1/tenants/{tenant_id}/native/memory-preferences`：调用者的个人开关。返回值同时给出生效状态和关闭原因（`space_disabled`、`user_disabled`），供界面提示使用。
   - 智能体草稿的 `budgets.memory` 校验：只接受 `enabled`（布尔值）。
   - 现有 `memory-capture` 接口保持不变。空间写入方式为 `explicit` 时，即使个人打开了自动抓取也不会排队（见决定 3）。
3. **Runtime 行为**（需确认）
   - 准备阶段：记忆关闭时不注入记忆索引，也不新建会话快照。已有快照保留，重新开启后继续复用。
   - 工具：记忆关闭时，从本次 Run 的工具定义里移除 `read_memory`、`search_memory`、`propose_memory_draft`、`start_long_term_update`，即使智能体绑定了这些工具。调用时网关会再检查一次，已在途的调用返回稳定错误码 `memory_disabled`。
   - 完成阶段：记忆关闭，或空间写入方式为 `explicit` 时，不排队自动抓取任务，抓取游标也不前移。
4. **界面**（按 WeKnora 页面复制，数据只来自 Nexus 接口）
   - 设置 → 记忆（空间，`memory`）：开关、写入方式。WeKnora 有而 Nexus 没有的项按决定 4 处理。普通成员只读。
   - 设置 → 我的记忆（`mymemory`）：
     - 个人开关。空间关闭时，显示「空间已关闭」的提示，开关不可用。
     - 自动提炼区块，作为 Nexus 扩展：开关、抽取模型、容量策略，对接现有 `memory-capture` 接口。
     - 待审核、生效中、已归档三个列表，对接现有的草稿审核、条目、停用、有效期、归档与恢复接口。
   - 智能体编辑器（`NexusAgentEditorModal.vue`）的基本信息分区：加入「长期记忆」开关，位置和文案沿用 WeKnora（`agent.editor.memoryEnabled`）。
   - 把 `memory`、`mymemory` 加入 `config/phase1.ts`。
5. 中文与英文文案。新增键在所有语言包中补齐（语言包键一致性测试要求）。

### 范围外

- 记忆规则本身（筛查、去重、墓碑、预算、版本、索引截断、检索排序），以及 PostgreSQL 全文索引。
- WeKnora 中 Nexus 尚无后端的功能：话题、记忆文档、整理（consolidate）、导出、清空、手动添加、语义召回、Embedding 模型、记忆参与检索、挖掘延迟与间隔、长期关注阈值、自定义挖掘规则、每人条数上限（Nexus 按字符预算限制）。
- 外部 Runtime（Codex、Claude Code、DeepSeek Harness）的记忆。

## 已确认的决定（全部采用推荐方案）

1. **空间开关的默认值**
   - 推荐：默认**开启**，写入方式默认 `auto`。现有空间升级后行为不变（记忆照常注入，已经开启自动抓取的成员继续抓取）。
   - 备选：与 WeKnora 一样默认关闭。这样隐私更保守，但所有空间的现有记忆会在升级后立即停止使用，需要管理员逐个开启。
2. **「记忆关闭」的含义**
   - 推荐：与 WeKnora 一致，读写全部停止：不注入索引，不提供记忆工具，网关拒绝记忆调用，也不排队抓取。已有条目、草稿和版本全部保留，「我的记忆」页仍可查看、审核、归档。
   - 备选：只停止写入（提议与抓取），保留读取。
3. **自动提炼的配置位置**
   - 推荐：空间写入方式决定是否允许自动提炼；抽取模型和容量策略仍按成员保存（现有 `memory_capture_settings`，在「我的记忆」中设置）。后端语义不变，模型授权仍按抓取任务所有者复核。
   - 备选：与 WeKnora 一样，抽取模型改为空间级设置，删除个人模型字段。这需要迁移现有数据，模型授权也要改为按空间判断。
4. **WeKnora 有而 Nexus 没有的设置项和列表**
   - 推荐：沿用对话框提案「完全复制界面、缺失功能占位」的做法：保留控件和位置，置为不可用并标注「规划中」，不发请求。
   - 备选：直接隐藏。

## 验收

- 空间、个人、智能体任一级关闭后，下一次 Run 的系统提示里没有记忆索引，工具定义里没有记忆工具，Run 完成后不产生抓取任务。三级全开时，行为与当前一致。
- 关闭前已发出的记忆工具调用在网关返回 `memory_disabled`。重新开启后复用已有会话快照，不重建。
- 空间写入方式为 `explicit` 时，个人已开启的自动抓取不排队，模型仍可提议草稿。
- 接口授权：非成员返回 404，成员写空间设置返回 403；参数校验返回 422；写入有审计。智能体关闭记忆只影响之后发布的版本。
- 设置 → 记忆、我的记忆不再显示占位页，所有请求都只指向 Nexus 接口（以测试断言请求路径）；智能体编辑器能保存并回显记忆开关。
- 后端 pytest 覆盖三级组合（至少 8 种开关组合中的关键情形）、工具过滤、网关拒绝、抓取不排队、迁移升降级；前端单元测试覆盖映射与禁用状态。
