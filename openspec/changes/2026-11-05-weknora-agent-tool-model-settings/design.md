# 设计：智能体设置、工具设置与模型设置

## 1. 前端：按 WeKnora 模板与样式重写 Nexus 版本

实施时核对发现，WeKnora 的 `AgentList.vue`（1878 行）、`AgentEditorModal.vue`（6831 行）、`ModelSettings.vue` 与 `ModelEditorDialog.vue` 深度依赖 WeKnora 专属的 store 与接口（`chatResources`、`organization`、`editorResources`、`modelProviders`、嵌入渠道、技能目录、知识库等），逐个替换数据层需要同时改写这些 store，风险与改动面都过大。因此按 AGENTS.md 的参考规则「按照逻辑重写」：新组件复制 WeKnora 对应分区的模板结构、类名与样式（LESS 原样拷贝），数据只来自 Nexus 接口。

- 智能体：`views/agent/NexusAgentList.vue`、`views/agent/NexusAgentEditorModal.vue`；表单映射 `views/agent/nexusAgentForm.ts`（纯函数）。
- 模型：`views/settings/NexusModelSettings.vue`、`views/settings/NexusModelEditorDialog.vue`；卡片与保存计划 `views/settings/nexusModelCards.ts`（纯函数）。
- 接口封装：`api/nexus-agents.ts`、`api/nexus-models.ts`。
- 路由 `/platform/agents` 与设置分区 `models` 指向新组件；WeKnora 原文件保留（既有源码测试仍读取它们），不再被这两个入口引用。

与 WeKnora 交互的已知差异：

- 温度滑块范围沿用 WeKnora 的 0–1（后端允许 0–2）；未单独设置时以模型档案的温度为初值。
- 最大迭代次数只提供数值（1–1000），不提供「不限制」：Nexus 的执行预算要求正数上限。
- 模型调用超时留空表示使用默认值 60 秒。
- 默认模型在卡片菜单中按作用域设置，卡片显示默认标签（WeKnora 无此概念；替代 `model-management` R5 中的「类型 × 作用域」表格）。

## 2. 智能体字段映射

| WeKnora 字段（`CustomAgent` / `config`） | Nexus（`AgentDraftInput`） | 说明 |
| --- | --- | --- |
| `id` | `id` | 只读，可复制 |
| `name`、`description` | `name`、`description` | |
| `config.agent_mode` | 固定 `smart-reasoning` | `runtime_type = native` |
| `config.system_prompt` | `instructions` | |
| `config.model_id` | `model_profile_version_id` | 只列 `chat` 类型且 `authorize_model` 通过的版本 |
| `config.temperature` | `budgets.generation.temperature` | 新增（决定 1）；0–2，空为不覆盖 |
| `config.reasoning_effort` | `budgets.generation.reasoning_effort` | 新增（决定 1）；`off/auto/minimal/low/medium/high/xhigh/max`（auto 跟随模型档案） |
| `config.max_completion_tokens` | `budgets.max_output_tokens` | 0 表示使用默认值 2048 |
| `config.max_iterations` | `budgets.max_rounds` | 上限 1000（沿用 `runs/settings.py` 校验） |
| `config.llm_call_timeout` | `budgets.model_timeout_seconds` | |
| `config.allowed_tools` | `resource_bindings[kind=tool]` | `resource_version_id = v1`，`source_tenant_id` 为当前空间 |
| `is_builtin`、`agent_type`、知识库/MCP/技能等字段 | 不映射 | 对应分区隐藏；保存时保留原有的非工具绑定（如技能），不被清空 |

保存时只替换 `kind=tool` 的绑定，其余绑定原样提交，避免编辑器覆盖其他入口写入的技能绑定。

新建智能体的初始值：模型取个人默认、其次空间默认（与 `create_native_agent` 一致）；预算与工具取用户的 Native 个人默认（`runs/settings.py`）。

## 3. 模型设置映射

WeKnora 的一条模型 = 名称 + 类型 + 地址 + Key；Nexus 的一条模型 = 供应商（名称、地址、Key、作用域）下的模型档案。

- **列表**：`GET model-settings` 返回的每个供应商下的每个模型展开为一张卡片；卡片显示供应商名称、可见范围与默认标签，不显示 Key。
- **类型**：`KnowledgeQA↔chat`、`Embedding↔embedding`、`Rerank↔rerank`、`VLLM↔vision`、`ASR↔speech`。
- **新建**：服务商下拉列出调用者可管理的供应商（个人供应商；管理员另含空间共享供应商）与「自定义（OpenAI 兼容接口）」。选已有供应商时复用其地址与 Key；选自定义时填写名称、地址、Key 与可见范围，先建供应商再建模型。失败重试复用本次已建的供应商，不重复创建（R5）。
- **编辑**：类型不可改；修改 Key 会轮换该供应商的 Key，对话框提示「同一供应商下的 N 个模型都会使用新 Key」。
- **删除**：调用 `DELETE .../models/{profile_id}`（停用，已发布引用保留）。供应商下无模型后不自动删除供应商。
- **测试**：未保存表单调用 `POST model-settings/test`；已保存模型复用已存 Key。
- **默认模型**：卡片菜单「设为 / 取消个人默认」「设为 / 取消空间默认」调用 `PUT model-settings/default`；空间默认只对空间共享模型、且 `can_manage_tenant` 时提供。
- 隐藏：来源切换（本地/Ollama）、WeKnora Cloud、内置模型、复制模型、调试抽屉、凭据子资源。

## 4. 后端

### 4.1 工具目录 `GET /api/v1/tenants/{tenant_id}/agent-tools`

参考 WeKnora `custom_agent.go` 的 `AvailableToolDefinitions`。成员可读；非成员 404。

```json
{
  "tools": [{"name": "todo", "label": "待办", "description": "...", "group": "base",
             "risk_level": "low", "read_only": false, "requires_approval": false,
             "enabled_in_tenant": true}],
  "default_tools": ["ask_user", "todo"],
  "can_enable_tools": true
}
```

- 来源为 `nexus_tools.builtins.builtins()`，不含延迟注册的执行类工具（沙箱未通过验收前不可见，沿用路线图第 8 步约束）。
- `label`、`group` 在 `packages/tools` 中按工具声明（新增可选字段，不影响 `ToolDefinition` 的执行语义）；未声明时 `group = base`、`label = name`。
- `default_tools` 取调用者的 Native 个人默认 `enabled_tools`。

### 4.2 智能体级生成参数（决定 1）

- `budgets.generation` 允许键：`temperature`（0–2）、`reasoning_effort`（枚举）。其他键 422。
- 发布时随版本冻结；`content_hash` 自然包含该字段。
- Native 运行准备阶段：`OpenAICompatibleModel` 的选项 = 模型档案 `options` ∪ 智能体 `generation`（智能体优先）。`reasoning_effort = off` 时不发送该字段。

### 4.3 删除与复制（决定 2）

- `DELETE /tenants/{tenant_id}/agents/{agent_id}`：`agents:write`；状态置为 `archived`，审计 `agent.archived`。已归档智能体不出现在列表；新建会话与提交 Run 返回 409；已有会话的消息仍可读取。
- `POST /tenants/{tenant_id}/agents/{agent_id}/copy`：`agents:write`；复制草稿（名称加「副本」后缀）为新的草稿智能体，不复制发布版本与共享关系；绑定逐项重新授权。

## 5. 风险

- `AgentEditorModal.vue` 体量大，映射集中在加载与保存函数，避免散改模板；以单元测试覆盖映射。
- 前端完整类型检查与构建在本机曾因内存不足失败（见 `2026-11-04-weknora-chat-dialog` 5.2），验证时需在内存充足的环境执行。
