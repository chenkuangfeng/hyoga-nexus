# 设计：长期记忆三级开关

以下按「推荐方案」描述；若决定 1–4 选择备选方案，实施前同步修订本文件。

## 1. 存储

| 层级 | 位置 | 字段 | 缺省 |
| --- | --- | --- | --- |
| 空间 | 新表 `memory_space_settings`（主键 `tenant_id`，外键级联删除） | `enabled`、`write_mode`（`explicit` / `auto`，CHECK 约束）、`updated_at`、`updated_by` | 无行 = `enabled=true`、`write_mode='auto'`（决定 1） |
| 个人 | 现有表 `memory_capture_settings` 新增列 `memory_enabled` | 布尔，`server_default` 为真 | 无行 = 开启 |
| 智能体 | 智能体版本 `budgets.memory` | `{"enabled": false}` | 缺省 = 继承 |

- 个人开关放在 `memory_capture_settings` 里，因为这张表本来就是「空间 + 用户」的记忆偏好，复用它可以避免再建一张同主键的表。自动抓取的 `enabled` 列保持原有含义。
- 迁移只新增表和列，不回填数据。降级时删除新增的表和列。PostgreSQL 与 SQLite 走同一套迁移。

## 2. 生效判断

`nexus_platform.memory` 新增门面函数，位于 `nexus_platform/memory/switches.py`：

```python
def memory_state(db, *, tenant_id, owner_id, agent_budgets) -> MemoryState:
    """返回 available、write_mode，以及关闭原因 space_disabled / user_disabled / agent_disabled（按此优先级取第一个）。"""
```

- 规则与 WeKnora `enabledScope` 相同，只是 Nexus 已经由调用方解析好主体，这里不再解析。检查顺序为空间、智能体、个人，任一项关闭即返回。
- 规则判断是纯函数，放在 `nexus_memory`（`switches.resolve(space, user, agent)`），便于不连数据库测试；读取配置行放在平台门面。
- 同一个 Run 的准备阶段只计算一次，并把结果放进 Run 的准备上下文。工具网关和完成阶段会重新读取配置，所以 Run 进行中途关闭开关，之后的调用也会被拒绝。

## 3. 使用点

| 使用点 | 文件 | 记忆关闭时 |
| --- | --- | --- |
| 索引注入 | `runs/preparation.py`（`session_index` 调用处） | 跳过，不新建快照 |
| 工具定义 | Native 工具装配处（实施时定位，按 `catalog.py` 的 `memory` 分组过滤） | 移除 `memory` 分组的全部工具 |
| 工具网关 | `runs/store.py` `read_memory` / `search_memory` / 提议入口 | 返回 `memory_disabled`，写审计 `memory.call_rejected` |
| 自动抓取 | `memory/capture.py` `enqueue_for_run` | 不排队，游标不动；`write_mode='explicit'` 时同样不排队 |
| 已排队任务 | 抓取 worker 领取任务时 | 任务以 `memory_disabled` 失败，不重试 |

工具过滤参照 WeKnora `agent_service.go:1325`：先移除，满足条件再加回。这样就算预设、旧配置或 API 调用方仍把这些工具写在列表里，也不会绕过开关。

## 4. 接口

```text
GET  /api/v1/tenants/{tenant_id}/memory-settings      → {enabled, write_mode, can_edit, updated_at}
PUT  /api/v1/tenants/{tenant_id}/memory-settings      ← {enabled, write_mode}
GET  /api/v1/tenants/{tenant_id}/memory-preferences   → {memory_enabled, effective, reason}
PUT  /api/v1/tenants/{tenant_id}/memory-preferences   ← {memory_enabled}
```

- 授权：非成员返回 404；写空间设置要求 owner 或 admin，否则返回 403。个人偏好只能读写本人的。
- `effective` 和 `reason` 不考虑智能体：页面是在没有智能体上下文的地方设置个人开关的。
- 审计：`memory.space_settings`、`memory.preferences`，元数据记录新值。

## 5. 前端

参照智能体与模型设置提案第 1 节的做法：WeKnora 页面依赖它自己的 store 和接口，所以新组件复制 WeKnora 的模板结构、类名和 LESS 样式，数据只来自 Nexus。

- `views/settings/NexusMemoryWorkspaceSettings.vue`：开关、写入方式（两个单选及说明）。WeKnora 其余项保留，置为不可用并标注「规划中」（决定 4）。没有写权限时整页只读。
- `views/settings/NexusMemorySettings.vue`：
  - 顶部：个人开关和使用说明弹层。空间关闭时显示 `memorySettings.agentDisabledHint` 风格的提示条，开关不可用。
  - 自动提炼区块（Nexus 扩展）：开关、抽取模型（只列有权使用的对话模型）、容量策略；空间写入方式为 `explicit` 时不可用并说明原因。
  - 标签页：待审核（草稿通过、拒绝）、生效中（停用、有效期、归档、版本与恢复）、已归档。WeKnora 的话题、文档、整理、导出、清空、手动添加按占位处理。
- `api/nexus-memory.ts`：上述接口，以及现有 `/memory`、`/memory-drafts/{id}/review`、`/memory/{id}`、`/memory/{id}/restore`、`/memory-capture` 的封装。
- `NexusAgentEditorModal.vue`：基本信息分区加入开关，`nexusAgentForm.ts` 负责映射：开启时不写 `budgets.memory`（继承），关闭时写入 `{enabled: false}`。
- 设置页的 `memory`、`mymemory` 分区改为指向新组件，原 WeKnora 文件保留（现有源码测试会读取它们）。
