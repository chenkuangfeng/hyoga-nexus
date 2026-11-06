# 规格：长期记忆开关

来源：`openspec/changes/archive/2026-11-05-memory-switches`（已实施并归档，2026-11-06）。

## 需求

### R1 三级开关
- 空间设置包含 `enabled` 与 `write_mode`（`explicit` / `auto`），空间没有设置行时视为 `enabled=true`、`write_mode='auto'`。
- 个人设置包含 `memory_enabled`，没有设置行时视为开启。
- 智能体版本的 `budgets.memory.enabled` 设为 `false` 时关闭记忆，不设置时继承；该值随版本发布冻结。
- 三者都允许时记忆才可用。关闭原因按 `space_disabled`、`agent_disabled`、`user_disabled` 的顺序取第一个。

### R2 记忆关闭时的 Run 行为
- 系统提示不注入记忆索引，也不新建会话快照；已有快照保留。
- 工具定义不包含 `memory` 分组的工具，即使智能体绑定了这些工具。
- 记忆工具调用返回 `memory_disabled`，并写审计。
- Run 完成时不排队自动抓取任务，抓取游标不前移；已排队的任务在领取时不调用模型，直接以 `memory_disabled` 跳过并完成。
- 已发布条目、草稿、版本与墓碑都不删除。

### R3 写入方式
- `write_mode='explicit'` 时不排队自动抓取任务，模型仍可提议草稿；`auto` 时按成员的自动抓取设置执行。

### R4 接口
- `GET/PUT /api/v1/tenants/{tenant_id}/native/memory-settings`：成员可读，owner 或 admin 可写；非成员返回 404，权限不足返回 403，参数非法返回 422；写入审计 `memory.space_settings`。
- `GET/PUT /api/v1/tenants/{tenant_id}/native/memory-preferences`：只读写调用者本人的设置，返回 `memory_enabled`、`effective`、`reason`；写入审计 `memory.preferences`。
- 智能体草稿的 `budgets.memory` 只接受 `enabled`（布尔值），否则返回 422。

### R5 界面
- 设置 → 记忆、我的记忆按 WeKnora 页面布局显示，所有请求都只发往 Nexus 接口；WeKnora 有而 Nexus 没有的项不可用并标注「规划中」。
- 空间关闭时，「我的记忆」显示提示，个人开关不可用；写入方式为 `explicit` 时，自动提炼区块不可用。
- 智能体编辑器的基本信息分区提供「长期记忆」开关，保存后能回显。
