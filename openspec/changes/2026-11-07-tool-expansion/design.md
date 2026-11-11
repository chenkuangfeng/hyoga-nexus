# 设计：工具扩展

状态：待确认。以下为推荐方案下的设计，决定变更后同步修改。

## 1. 工具分组与两层门控

```text
ToolDefinition.group ──► ToolGroupRegistry (id, label, default_enabled, availability)
                               │
Run 准备（preparation.py）：  绑定 ─► 过滤1：group.availability(ctx) 为假 → 丢弃（编辑器显示原因）
                                   └► 过滤2：NativePolicy.tool_groups_enabled[group] 为假 → 丢弃
                               │
网关（每次调用）：            实时授权 → 访问级别 → 参数 → 守卫 → 审批 → 执行   （不变，开关不放宽）
```

- `availability(ctx) -> Availability(ok, reason)` 是纯函数，输入是部署状态与 Run 上下文，不做 IO 的部分由调用方预先装配进 `ctx`：沙箱验收结果、已配置的搜索后端、智能体绑定的知识库类型。reason 是稳定代码（`sandbox_disabled`、`sandbox_not_accepted`、`web_backend_missing`、`wiki_kb_not_bound`），前端翻译成文案。
- 现有门控（`script_tool_on`、`memory_on`、`knowledge_bound`）改为各组的 `availability`，行为不变，用现有测试证明。
- `tool_groups_enabled` 缺省值取各组 `default_enabled`；老智能体版本没有这个字段，按缺省处理，因此 `sandbox`、`web` 等新组对既有智能体默认不出现。智能体版本是不可变的，开关变化产生新版本，已发布版本不被悄悄改变。
- 一致性测试：遍历 `builtins()` 注册表，断言每个工具有合法 `group`、属于 `BUILTIN_TOOL_NAMES`，且 `BUILTIN_TOOL_NAMES` 里每个名字要么已注册，要么在「待实现」清单里（如 Wiki 工具）。

## 2. 沙箱

### 2.1 包结构（`packages/sandbox`）

| 模块 | 职责 |
| --- | --- |
| `contracts` | `CommandExecutorPort`（`run(spec) -> Result`、`start/poll/cancel` 后台作业）、`FileStorePort`（`read/write_atomic/list/stat/search`）、`SandboxLease`、`VirtualPath` |
| `backends/docker` | 每个（租户，会话）一个容器；工作区为命名卷；`exec` 进入容器 |
| `backends/local` | 仅开发模式，不能用于多用户；首版只作为端口的测试替身，不开放给工具组 |
| `paths` | 虚拟路径 ↔ 容器路径；拒绝 `..`、符号链接逃逸、绝对宿主路径 |
| `lease` | 租约：Run 持有，结束或取消释放；空闲 `idle_seconds` 后回收容器，卷保留到配额与保留期 |
| `acceptance` | 隔离验收与连通探测 |
| `artifacts` | 扫描 `/outputs` 并登记 |

### 2.2 Docker 后端参数

非 root 用户；`--network none`（部署可改）；只读根文件系统，`/workspace`、`/outputs` 为可写卷，`/tmp` 为 tmpfs；`--cap-drop ALL`、`no-new-privileges`、默认 seccomp；`--cpus`、`--memory`（含 swap 上限）、`--pids-limit`；每次 `exec` 有墙钟超时，超时或取消时杀掉整个进程组；输出每流上限，超出丢弃并标记；不挂载宿主目录，不继承服务进程环境变量，子进程环境从零构造（沿用 `skill_scripts` runner 的做法）。

### 2.3 验收（`acceptance`）

每项是一个真实的容器内探测，不是配置检查：

| 项 | 探测 |
| --- | --- |
| 资源限制 | 内存分配超限被 OOM 杀；`while true` 超时被终止；fork 炸弹被 pids 限制；超大输出被截断 |
| 网络隔离 | 配置为 `none` 时，TCP 连接与 DNS 解析都失败 |
| 租户隔离 | 租户 A 写入的文件在租户 B 的租约里不可见；路径穿越被拒绝 |
| 清理 | 租约释放后容器与进程消失，卷按保留期处理 |
| 崩溃残留 | 强制杀掉 worker 后重启，能发现并回收遗留容器 |
| 连通 | 写 → 读 → 删一个探测文件 |

结果写表 `sandbox_acceptance(backend, image_digest, passed, items, checked_at)`。镜像摘要变化、后端配置变化时旧结果失效。入口：worker 启动自检，以及 `uv run python -m nexus_worker sandbox-check` 手动执行。`sandbox` 组可用性 = `[sandbox].enabled` 且最近一次验收对当前镜像与配置通过。

### 2.4 工具实现要点

- 文件：`sandbox_read_file` 按行或字符分页，返回总大小；二进制拒绝并提示用别的方式；`sandbox_write_file` 临时文件加原子替换；`sandbox_edit_file` 要求 `old` 在文件中恰好出现一次，否则返回出现次数让模型加上下文（参考 DeepSeek `tool-str-replace-editor`）。
- 命令：参数 `command`、`cwd`（虚拟路径）、`timeout_seconds`（不超过智能体上限）；返回 `exit_code`、截断标记、`duration`；stdout 与 stderr 分开保留头尾。
- 后台作业：`sandbox_exec_async` 立即返回 `job_id`；`sandbox_job_wait(job_id, timeout)` 返回新增输出与状态；作业生命周期不超过所属 Run，Run 终态时取消仍在跑的作业并标记。与路线图 3.24（异步工具）的关系：本变更只做 Run 内作业，不做跨 Run 的结果回投；3.24 评估时再合并。
- 公开投影：命令与文件工具的 `public_result` 只返回上述摘要字段，不含宿主路径。

### 2.5 配置

`configs/nexus.toml`：

```toml
[sandbox]
enabled = false            # 部署开关
backend = "docker"
image = "..."              # 实施时固定镜像与摘要
cpus = 1.0
memory_mb = 512
pids = 128
network = "none"           # none | bridge（打开后 sandbox_exec 风险升为 destructive）
idle_seconds = 900
workspace_quota_mb = 512
exec_timeout_max_seconds = 120
```

`NativePolicy` 新增 `tool_groups_enabled: dict[str, bool]`、`sandbox_exec_timeout_seconds`（默认 30）、`sandbox_output_limit`（默认 20000 字符）。设置页标签同步补齐。

## 3. 调度

```python
class ConcurrencyHint(NamedTuple):
    mode: Literal['parallel', 'exclusive', 'serial']
    key: str | None = None   # serial 时同 key 排队，例如 sandbox 虚拟路径
```

`execute_batch` 从当前位置起逐个取调用，按 `definition.concurrency(arguments)`（未声明则按现有 `read_only and idempotent` 推出）分类：连续的 `parallel` 组成并行批（上限仍为 8），`serial` 调用按 key 排队、不同 key 可并行，`exclusive` 先排空再单独执行。结果与 `tool.before/after` 钩子仍按模型顺序。参数在分类前已由网关规范化（`prepare_arguments`），分类函数接收规范化后的参数；解析失败的调用按 `exclusive` 处理。审批挂起沿用现有恢复路径（`recovery.resume_tools`），串行 key 不跨恢复保存。

## 4. 渐进加载

触发：绑定工具的 schema 估算 token 数超过上下文窗口的 `tool_search_threshold_pct`（默认 10%）。被延迟的工具：`source == 'mcp'` 和声明 `deferrable=True` 的大型工具组；`base` 与现有内置工具永不延迟。

- Run 开始时：工具块 = 非延迟工具 + `tool_search` + `tool_describe` + `tool_call`；系统提示附一份名称加一句话的目录，受 `listing_max_tokens` 约束，超限降级为只列组名。
- `tool_search(queries)`：在延迟目录里做关键词检索，返回名称与摘要，次数与结果数有上限。
- `tool_describe(names)`：返回完整 schema（经 sanitize）。
- `tool_call(name, arguments)`：网关先解开，再按真实工具名执行 `authorize → 访问级别 → 预处理 → 守卫 → 审批 → 执行`。真实工具必须在智能体绑定里；未绑定或被组开关过滤的工具即使知道名字也调不通。循环检测、审计、事件使用真实工具名。
- 三个桥接工具自身为 `read`、可并行，其中 `tool_call` 的调度提示取自被调用的真实工具。

## 5. Schema 清洗

`sanitize(schema, provider)` 返回深拷贝，规则从 Hermes `schema_sanitizer.py` 移植：属性名不匹配 `^[a-zA-Z0-9_.-]{1,64}$` 时改写并保留映射（调用返回时还原）；对象缺 `properties` 时补空；顶层 `anyOf` / `oneOf` 展开或合并；`default` 与 `$ref` 并存时去掉 `default`；布尔式 `required` 提升。按供应商开关，调用点在 `nexus_runtimes/native/models` 序列化工具定义之前。

## 6. Web

- `nexus_tools/web/` 下 `search`（后端注册表 `SearchBackend.search(query, limit, ctx) -> list[Hit]`）、`fetch`（HTTP 抓取 + 正文抽取）。
- 出站校验：把 `runtimes/native/models/network.py` 的地址校验抽到 `nexus_core.net`（只依赖标准库），模型连接与 `web_fetch` 共用。每一跳（含重定向）都校验解析后的 IP，拒绝回环、私网、链路本地、元数据地址；限制协议与端口；总大小与超时上限。
- 返回：`{url, title, text}`，文本经注入扫描并带外部内容前缀；搜索结果同样带前缀。

## 7. Wiki 组

本变更交付：组与子组定义、`availability = 智能体绑定了 wiki 类型库`、风险映射、目录占位（「待实现 · K6」）。九个工具的实现、持久化与前端属于知识库提案 K6.1。读类可并行；`wiki_write_page` / `wiki_replace_text` / `wiki_rename_page` 以页面路径为 `serial` key。

## 8. 协作与定时（阶段 G，实施前补充）

此处只记录已定的约束，具体接口在阶段开始前补全并再次确认。

- `delegate_task`：子 Run 的 `NativePolicy` = 父级策略收紧后的副本（`tool_access` 不低于父级，工具集 ⊆ 父级绑定，`collab` 组本身不继承以禁止递归）；子 Run 的审批请求冒泡为父会话的审批；预算从父预算扣除；结果以单条工具结果返回父级，过长走外置。
- `cronjob`：任务保存（所有者、智能体版本、提示、计划、时区、状态）；worker 的调度器按计划创建 Run；无人值守 Run 的 `tool_access` 强制 `read_only` 或「不允许需要审批的工具」，拒绝时记录审计而不是挂起；创建与修改需要审批（`write`）；每用户任务数、最小间隔与每日运行数有上限；提示入库前扫描。

### 8.2a 定时任务的 REST 与界面（待确认，2026-11-11 补充）

**现状**：`cron_jobs`、规则（interval / daily / weekly）、服务（创建、列表、暂停 / 恢复 / 删除、到点触发）和 `cronjob_*` 工具已实现，但只有模型能创建和管理任务，用户看不到、改不了。前端 `/platform/automations` 仍是占位页；仓库里复制了 WeKnora 的 `views/automation/*`（约 2300 行）与 `api/automation.ts`，它们面向 WeKnora 的完整自动化模型（cron 表达式、一次性触发、漏触发与重叠策略、每次运行记录、审批授权、通知），与 Nexus 刻意收窄的任务模型差距很大。

**决定点**（括号内为推荐）：

| 编号 | 问题 | 选项 |
| --- | --- | --- |
| C1 | 界面形态 | 新建精简的 Nexus「定时任务」页（推荐）；或把 WeKnora 自动化页适配到 Nexus，不支持的控件标「待实现」 |
| C2 | 创建时如何指定智能体 | 选一个已发布智能体，任务固定在其**当前已发布版本**；创建后不能换智能体（推荐，因为会话绑定智能体版本）；或允许换并新建会话 |
| C3 | 可见范围 | 只管理本人的任务（推荐）；或管理员可查看 / 暂停他人任务 |
| C4 | 「立即运行」 | 纳入（推荐，不改变下次触发时间，1 分钟内只能点一次）；或不做 |
| C5 | 运行记录 | 取任务会话里的 Run 列表，点击进入该会话（推荐，不新建表）；或新建任务运行表 |
| C6 | 触发规则 | 沿用三种规则，界面提供「预览接下来 3 次触发」（推荐）；或加入 cron 表达式 |

**接口**（`/api/v1/tenants/{tenant_id}/schedules`，仅空间成员，只能操作自己的任务，他人的任务一律按不存在处理）：

| 方法与路径 | 用途 |
| --- | --- |
| `GET /` | 本人任务列表，含状态（`active` / `paused` / `suspended`）、规则描述、下次与上次运行时间、次数、`last_error` |
| `POST /` | 创建：`name`、`prompt`、`agent_id`、`schedule`（规则）、`timezone`；服务端取该智能体当前已发布版本，没有则 `schedule_agent_unpublished` |
| `GET /{id}` | 详情，额外返回完整 `prompt`、规则对象、智能体名称与固定的版本号、任务会话 id |
| `PATCH /{id}` | 改 `name`、`prompt`、`schedule`、`timezone`；改规则或时区会按当前时间重算 `next_run_at`；改 `prompt` 重新扫描注入措辞；`suspended` 的任务编辑后仍需 `resume` |
| `POST /{id}/pause`、`/resume`、`DELETE /{id}` | 沿用 `change_state`，规则与限额不变 |
| `POST /{id}/run` | 立即以任务会话发起一次运行（幂等键 `cron-now:{id}:{随机}`），更新 `last_run_at`、`last_run_id`、`run_count`，不改 `next_run_at`；`paused` 与 `suspended` 也允许；距上次运行不足 60 秒返回 `schedule_run_too_soon` |
| `GET /{id}/runs?limit=` | 任务会话里的 Run（状态、创建与结束时间、错误码），新的在前，最多 50 条 |
| `POST /preview` | 校验 `schedule` + `timezone` 并返回接下来最多 5 次触发时间（UTC 与本地），不写库 |

- 错误码沿用 `ScheduleError.code`：`schedule_not_found` → 404，`schedule_limit_reached` → 409，`schedule_run_too_soon` → 429，其余 `schedule_*` → 422，响应带 `code` 与 `detail`。
- 服务层新增 `get_job`、`update_job`、`run_now`、`list_runs`、`preview`，创建仍走 `create_job`；REST 与工具共用同一套规则、限额（每人 10 个活跃）、提示扫描与审计（新增 `schedule.updated`、`schedule.run_now`）。
- 不要求智能体开启 `schedule` 工具组：该开关管的是**模型**能否创建任务，用户自己管理不受影响。
- 无人值守不变：任务运行拿不到审批和提问机会，界面在创建与详情处固定提示。

**前端**（`/platform/automations` 由占位页改为新页，路由名 `automationList` 不变）：

- `api/nexus-schedules.ts`（请求）与 `views/schedule/scheduleModel.ts`（纯函数：规则表单 ↔ 规则对象、状态到标签与可用操作、错误码到文案），不依赖 Vue 以便 `tsx --test`。
- `NexusScheduleList.vue`：列表（名称、智能体、规则描述、状态标签、下次运行、上次运行与次数）与行内操作（暂停 / 恢复、立即运行、编辑、删除，删除有确认）；`suspended` 行显示原因；空状态引导创建。
- `NexusScheduleDialog.vue`：创建 / 编辑；字段为名称、智能体（只列已发布的，编辑时只读）、提示词（字数上限 4000，显示无人值守说明）、规则（间隔 / 每天 / 每周三种单选加对应输入）、时区（默认浏览器时区）；规则变化时请求 `preview` 显示接下来 3 次触发。
- `NexusScheduleRuns.vue`（抽屉）：最近运行列表，行内链接到 `/platform/chat/{session_id}`。
- 复制来的 WeKnora `views/automation/*` 与 `api/automation.ts` 保持不动、不接路由，文档中注明未启用，需要时再单独适配（C1 选另一方案则相反）。
- 文案六种语言一次加齐；表格与操作按钮带可访问名称；状态不只靠颜色。

**不做**：cron 表达式、一次性触发、漏触发与重叠策略配置、通知中心、管理员代管、任务运行专用表、多会话模式（每次新会话）。这些都留给路线图 9.4 外部事件触发一起评估。

**测试**：服务层（更新重算下次时间、更新触发扫描、`run_now` 不改 `next_run_at` 且 60 秒节流、`list_runs` 只见本任务会话、他人任务 404）；接口（权限、错误码映射、`preview` 不写库、未发布智能体）；前端纯函数与对话框交互（沿用 `node:test` 组件测试惯例）。

**风险**：`run_now` 在会话忙时会排队（沿用忙会话队列），文案需说明；任务固定版本，智能体后来更新不影响它，界面显示固定的版本号并提示新建任务以使用新版本。

## 9. 迁移与兼容

- 新表：`sandbox_acceptance`、`artifacts`（若与产物提案重合，复用其结果）。沿用 Alembic 升降级并测试。
- `ToolDefinition` 新增字段全部带默认值（`group='base'`、`source='builtin'`、`concurrency=None`、`deferrable=False`），旧调用点和测试不改。
- `catalog.TOOL_GROUPS` 删除后，`/tools/catalog` 响应字段 `group` 保持，另增 `availability` 与 `reason`。
- 老智能体版本无 `tool_groups_enabled`：按缺省处理。

## 10. 测试

`tests/test_tool_groups.py`（分组、两层门控、一致性）、`tests/test_sandbox_*.py`（路径、租约、工具；容器相关测试在无 Docker 时跳过并标明）、`tests/test_tool_scheduling.py`、`tests/test_tool_search.py`、`tests/test_schema_sanitize.py`、`tests/test_web_tools.py`；沙箱验收报告作为文件留存。
