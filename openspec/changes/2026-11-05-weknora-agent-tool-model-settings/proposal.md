# 严格参考 WeKnora 实现智能体设置、工具设置与模型设置

## 状态

已确认（2026-11-05）：四项决定全部采用推荐方案。父提案：`openspec/changes/2026-11-02-weknora-parity/`（第 5 阶段「智能体编辑器」与第 2 阶段「设置 · 模型管理」的子提案）。

## 原因

- `/platform/agents` 仍是「规划中」占位页（`router/index.ts` 指向 `PlannedPage`）。`apps/web/src/views/agent/AgentList.vue`、`AgentEditorModal.vue` 已是 WeKnora 前端副本（6831 行，与参考版本一致），但调用的是 WeKnora 接口（`/api/v1/agents`、`/api/v1/agents/tools`、`/api/v1/agents/type-presets` 等），Nexus 后端不提供。
- 设置页的 `models` 分区不在 `config/phase1.ts` 的已实现集合中，显示占位页；`ModelSettings.vue` 与 `ModelEditorDialog.vue` 调用 WeKnora 的 `/api/v1/models`，而 Nexus 的模型接口是 `/api/v1/tenants/{tenant_id}/model-settings`（供应商 + 模型档案，见 `openspec/specs/model-management/spec.md`）。
- 用户只能通过对话页选择已发布智能体，无法在界面上创建、编辑智能体，也无法为智能体选择工具和生成参数。

参考源码：WeKnora `frontend/`，固定版本 `e1f9a6166`（本地副本 `/project/opensource/knowledge-base/WeKnora`）。
- 智能体：`views/agent/AgentList.vue`、`views/agent/AgentEditorModal.vue`、`api/agent/index.ts`；后端 `internal/handler/custom_agent.go`（`GET /agents/tools` 的目录形态）。
- 模型：`views/settings/ModelSettings.vue`、`components/ModelEditorDialog.vue`、`api/model/index.ts`。

## 范围

### 范围内

1. **智能体列表**（`/platform/agents`，`AgentList.vue`）
   - 卡片列表、搜索、排序、新建、编辑、复制、删除（见决定 2）、从卡片开始对话（创建平台会话后跳转 `/platform/chat/:id`）。
   - 数据来自 `GET /tenants/{tenant_id}/agents`；管理员看到草稿，成员只看到已发布版本（沿用后端现有可见性判断）。
2. **智能体编辑器**（`AgentEditorModal.vue`，左侧分组导航 + 右侧分区，布局与交互不变）
   - **基本信息**：智能体 ID（复制）、名称、描述。运行模式固定为「智能推理」（Nexus 只有 Native ReAct 运行时），模式单选与「智能体类型预设」隐藏。
   - **提示词**：系统提示词（映射 `instructions`）。WeKnora 的上下文模板、改写、兜底提示词属于快速问答模式，隐藏。
   - **模型配置**：对话模型（只列 `chat` 类型、调用者有权使用的模型）、温度、最大输出 Token、思考强度、最大迭代次数、模型调用超时。ReRank 与问题理解模型依赖知识库，隐藏。
   - **工具配置**：按分组展示 Nexus 内置工具目录（名称、说明、风险等级、是否需审批、是否只读）；勾选结果写入智能体的工具绑定。空间未启用的工具显示为不可选并提示（见决定 4）。
   - 其余分区（多轮对话、问题推荐、知识库、检索、联网搜索、多模态、MCP、技能、共享、IM/嵌入渠道）本提案隐藏，分别随路线图第 6、7、9 步与后续子提案开放。
3. **模型设置**（设置 → 模型管理，`ModelSettings.vue` + `ModelEditorDialog.vue`）
   - 类型标签页、卡片列表、添加 / 编辑 / 删除、连接测试、默认模型（类型 × 作用域），与 WeKnora 的页面一致。
   - 前端适配层把 WeKnora 的「模型（含地址与 Key）」映射为 Nexus 的「供应商 + 模型档案」（见 design.md 第 3 节），后端模型接口不改。
   - 将 `models` 加入 `config/phase1.ts` 的已实现分区。
4. **后端（需确认，涉及 API 契约与 Runtime 行为）**
   - 新增 `GET /api/v1/tenants/{tenant_id}/agent-tools`：智能体可选工具目录。
   - 智能体草稿 `budgets` 新增 `generation` 分组（`temperature`、`reasoning_effort`），Native 运行时以智能体值覆盖模型档案选项（见决定 1）。
   - 新增智能体删除（见决定 2）与复制接口。
5. 中文与英文文案（沿用 vue-i18n 现有键，新增键两种语言同时补齐）。

### 范围外

- 快速问答（RAG）模式、知识库与检索、联网搜索、MCP、技能绑定界面、多模态、问题推荐、共享与发布渠道。
- Ollama、WeKnora Cloud、内置模型目录、模型调试抽屉（`ModelDebugDrawer`）、协议兼容覆盖 JSON。
- 非 `chat` 类型模型的实际调用（随路线图第 6 步）。
- 外部 Runtime（Codex、Claude Code、DeepSeek Harness）的智能体配置。

## 已确认的决定（全部采用推荐方案）

1. **智能体级生成参数**：WeKnora 把温度与思考强度放在智能体上；Nexus 目前只在模型档案的 `options` 中读取（`openai_compatible.py`）。
   推荐：智能体 `budgets.generation` 保存 `temperature` 与 `reasoning_effort`，Native 运行时优先使用智能体值，未设置时回退模型档案选项。随版本发布冻结，已发布版本与已有会话不受影响。
   备选：不改 Runtime，模型配置区只显示模型档案的值（只读）。
2. **删除智能体**：Nexus 目前没有删除接口。
   推荐：软删除（状态改为 `archived`）——列表与新建会话中不再出现，已有会话可查看历史但不能再提交新的 Run；需要 `agents:write` 权限并写审计。
   备选：本提案不做删除，卡片隐藏删除菜单。
3. **保存与发布**：WeKnora 编辑器只有「保存」；Nexus 是「草稿 + 发布」。
   推荐：编辑器「保存」= 保存草稿并立即发布新版本（与 WeKnora 交互一致）；发布失败时保留草稿并显示原因。
   备选：保留两个按钮（保存草稿 / 发布）。
4. **未在空间启用的工具**：工具需先由管理员在空间启用（`POST .../tools/{name}/enable`）才能绑定。
   推荐：目录中显示所有内置工具；未启用的工具对管理员显示「启用」按钮（调用已有接口），对成员显示为不可选并提示联系管理员。
   备选：只显示已启用的工具。

## 验收

- `/platform/agents` 可创建、编辑、复制、删除（按决定 2）智能体，并能从卡片开始对话；编辑器的基本信息、提示词、模型配置、工具配置四个分区与 WeKnora 布局一致，其余分区不出现。
- 工具配置保存后，下一次 Run 的工具定义只包含已勾选且已授权的工具；撤销空间启用后下一次调用被拒绝（沿用网关复核）。
- 模型配置中的温度与思考强度在 Run 的模型请求中生效（按决定 1）；更改已发布智能体的配置不影响已有会话正在使用的版本。
- 设置 → 模型管理不再显示占位页；添加、编辑、删除、测试、默认模型行为满足 `model-management` 规格 R1–R5，API Key 不回显、不写入浏览器存储。
- 前端不再调用 `/api/v1/agents*`、`/api/v1/models*` 等 WeKnora 接口（以测试断言请求路径）。
- 后端 pytest 覆盖新增接口的授权（非成员 404、角色不足 403）、校验（422）、审计；前端单元测试覆盖适配层映射。
